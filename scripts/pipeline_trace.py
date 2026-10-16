"""Render one pipeline run as a flat, readable trace.

Produces the graph facts the model was given, each stage's raw output, the PDDL,
the plan, and a verdict - in one file, with the errors marked. Written for
reading side by side with a supervisor, not for machine consumption (report.json
already covers that).

Entities are selected per task rather than hardcoded: whatever the ground-truth
object_states name, plus whatever appears in the goal stage, plus anything the
findings implicate. Dumping all 47 objects would bury the signal.
"""

import json
import os
import re

from scripts.pddl_utils import parse_facts, _section


def _relevant_entities(task_row: dict, stages: dict, findings: list) -> set:
    ents = set()
    for spec in (task_row.get("object_states") or []):
        ents.add(str(spec.get("name", "")).lower())
        for c in (spec.get("contains") or []):
            ents.add(c.lower())
    # Only the GOAL stage, not relation: relation legitimately dumps half the
    # scene, and pulling entities from it makes "task-relevant" meaningless.
    for f in parse_facts(stages.get("goal", "")):
        ents |= {a.lower() for a in f[1:] if not a.startswith("?")}
    # Only findings that identify a SPECIFIC problem object. INVENTED_OBJECT
    # and UNDECLARED_OBJECT can each name dozens of symbols, which would drag
    # the whole scene back into the "task-relevant" sections.
    FOCUS = {"MISSING_AFFORDANCE", "CONTRADICTION", "DROPPED_CRITICAL_FACT",
             "TASK_NOT_ACHIEVED", "HALLUCINATED_ACTION"}
    for f in findings:
        if f.get("code") in FOCUS:
            ents |= set(re.findall(r"[A-Za-z]+_\d+", f.get("fact", "").lower()))
    ents = {e for e in ents if e}

    # A sane goal names a handful of entities. When a stage degenerates - e.g.
    # FloorPlan201 task 3, where the goal stage emitted (at-location Laptop_1 X)
    # for EVERY object in the room - the set becomes the whole scene and the
    # trace stops being readable. Fall back to the ground-truth objects, and let
    # the caller flag the degeneration.
    if len(ents) > 10:
        core = set()
        for spec in (task_row.get("object_states") or []):
            core.add(str(spec.get("name", "")).lower())
            for c in (spec.get("contains") or []):
                core.add(c.lower())
        for f in findings:
            if f.get("code") in {"MISSING_AFFORDANCE", "TASK_NOT_ACHIEVED"}:
                core |= set(re.findall(r"[A-Za-z]+_\d+", f.get("fact", "").lower()))
        if core:
            return core
    return ents


def _matches(name: str, ents: set) -> bool:
    """Match a sanitized symbol (Book_1) against a bare name (book) or another
    symbol. Deliberately strict: a loose prefix test matches nearly everything
    and turns the "task-relevant" sections into a dump of the whole scene."""
    n = name.lower()
    for e in ents:
        if not e or len(e) < 3:
            continue
        if n == e or n.startswith(e + "_") or e.startswith(n + "_"):
            return True
        # bare "laptop" should match "laptop_1" and vice versa
        if n.rsplit("_", 1)[0] == e.rsplit("_", 1)[0]:
            return True
    return False


def write_trace(path, task_row, args, robots, triplets, gt, stages,
                pddl, plan_actions, plan_solved, findings, repair_changes,
                model, fixture):
    """Write the trace. Returns the path written."""
    O, W = [], None
    W = lambda s="": O.append(s)
    bar = "=" * 78
    ents = _relevant_entities(task_row, stages, findings)

    W(bar); W("KG-LaMMA-P PIPELINE TRACE"); W(bar)
    W(f"task     : {task_row['task']}")
    W(f"dataset  : {args.dataset}  index {args.task_index}")
    tier = ("vague" if "vague" in args.dataset else
            "complex" if "pddl" in args.dataset else "easy")
    W(f"tier     : {tier}   (MAT-THOR: easy / complex / vague)")
    W(f"scene    : AI2-THOR FloorPlan{args.floor_plan}")
    W(f"fixture  : {fixture}")
    for r in robots:
        W(f"robot    : {r['name']} = dataset robot{r['dataset_id']}  {r['skills']}")
    W(f"model    : {model}   temperature 0  seed 0  repetition_penalty 1.05")
    W(f"gt states: {task_row.get('object_states')}")
    W()

    # ---- graph -------------------------------------------------------------
    W(bar); W("KNOWLEDGE GRAPH  (built mechanically from AI2-THOR metadata, no LLM)"); W(bar)
    W(f"property {len(triplets['property'])}   relation {len(triplets['relation'])}   "
      f"reach {len(triplets['reach'])}   entities {len(gt['entities'])}")
    W()
    goal_ents = set()
    for f in parse_facts(stages.get("goal", "")):
        goal_ents |= {a.lower() for a in f[1:] if not a.startswith("?")}
    if len(goal_ents) > 10:
        W(f"!! the goal stage named {len(goal_ents)} distinct entities - a well-formed")
        W("!! goal for this task needs a handful. Listing ground-truth objects only.")
        W()
    W("-- affordances of task-relevant objects --")
    for a, r, b in triplets["property"]:
        if r == "has_capability" and not a.startswith("robot") and _matches(a, ents):
            W(f"   (has_capability {a} {b})")
    W()
    W("-- open/closed state (only meaningful for openable objects) --")
    openable = {o for o, c in gt["capabilities"] if c == "openable"}
    shown = False
    for a, r, b in triplets["property"]:
        if r == "isOpen" and _matches(a, ents) and a.lower() in openable:
            shown = True
            W(f"   (isOpen {a} {b})" + ("   [CLOSED - needs (openable) to be opened]"
                                        if not b else "   [ALREADY OPEN]"))
    if not shown:
        W("   (no openable object among the task-relevant set)")
    # property_graph emits isOpen for EVERY object, so a pen and the floor also
    # carry isOpen=False. Those are not "closed" in any useful sense and are
    # omitted here; property_prompt still renders them as (isClosed X), which is
    # noise the model has to ignore.
    W()
    W("-- robot skills --")
    for a, r, b in triplets["property"]:
        if a.startswith("robot"):
            W(f"   (has_capability {a} {b})")
    W()
    W("-- relations touching task objects --")
    for a, r, b in triplets["relation"]:
        if _matches(a, ents) or _matches(b, ents):
            W(f"   ({r} {a} {b})")
    W()

    # ---- stages ------------------------------------------------------------
    for key, title in [("goal", "STAGE 1 - GOAL"), ("relation", "STAGE 2 - RELATION"),
                       ("property", "STAGE 3 - PROPERTY"), ("reach", "STAGE 4 - REACH"),
                       ("pddl_raw", "STAGE 5 - PDDL")]:
        if key not in stages:
            continue
        W(bar); W(title); W(bar)
        txt = stages[key].strip()
        lines = txt.splitlines()
        if key == "reach" and len(lines) > 8:
            W("\n".join(lines[:8])); W(f"   ... {len(lines)-8} more lines")
        elif key == "pddl_raw" and len(lines) > 60:
            W("\n".join(lines[:20])); W(f"   ... {len(lines)-20} more lines "
                                        "(full text in 5_pddl.out.txt)")
        else:
            W(txt)
        stage_f = [f for f in findings if f["where"].endswith(key.replace("_raw", ""))
                   or f["where"] == f"{'12345'[['goal','relation','property','reach','pddl_raw'].index(key)]}_{key.replace('_raw','')}"]
        for f in stage_f:
            W(f"   >>> {f['code']}: {f['fact']}")
        W()

    # ---- pddl --------------------------------------------------------------
    W(bar); W(f"PROBLEM PDDL  (after {len(repair_changes)} syntax-only repairs)"); W(bar)
    if pddl:
        for pred in ("openable", "pickupable", "sliceable", "toggleable"):
            present = re.search(rf"\(\s*{pred}\s", pddl, re.I) is not None
            expected = [o for o, c in gt["capabilities"]
                        if c == pred and _matches(o, ents)]
            if expected:
                W(f"({pred} ...) for {expected}:  "
                  + ("PRESENT" if present else "ABSENT   <<< dropped by the model"))
        g = re.search(r"\(:goal.*?\n\s*\)", pddl, re.DOTALL)
        W(); W(g.group(0) if g else "<no :goal found>")
    else:
        W("<no usable PDDL produced>")
    W()

    # ---- plan --------------------------------------------------------------
    W(bar); W("FAST DOWNWARD PLAN"); W(bar)
    if plan_solved and plan_actions:
        skills = {r["name"].lower(): {s.lower() for s in r["skills"]} for r in robots}
        for act, argv in plan_actions:
            note = ""
            rb = next((x for x in argv if x.startswith("robot")), None)
            if rb and rb in skills and act not in skills[rb] and act != "gotoobject":
                note = f"   <<< {rb} lacks {act} (domain gap, not hallucination)"
            W(f"   ({act} {' '.join(argv)}){note}")
        for f in findings:
            if f["code"] in ("TASK_NOT_ACHIEVED", "HALLUCINATED_ACTION"):
                W(f"   >>> {f['code']}: {f['fact']}")
    else:
        W("   <no plan - see FINDINGS>")
    W()

    # ---- verdict -----------------------------------------------------------
    W(bar); W("VERDICT"); W(bar)
    W(f"planner  : {'Solution found, ' + str(len(plan_actions)) + ' steps' if plan_solved else 'NO PLAN'}")
    achieved = not any(f["code"] == "TASK_NOT_ACHIEVED" for f in findings)
    W(f"task     : {'accomplished' if (plan_solved and achieved) else 'NOT ACCOMPLISHED'}")
    W()
    W(f"findings : {len(findings)}")
    by = {}
    for f in findings:
        by.setdefault(f["code"], []).append(f)
    for code, items in sorted(by.items(), key=lambda kv: -len(kv[1])):
        W(f"   {code:<24} x{len(items):<4} e.g. {items[0]['fact'][:52]}")
    W()
    W("the knowledge graph is derived mechanically from AI2-THOR metadata.")
    W("every fact above marked <<< was present in the graph and in the prompt.")

    with open(path, "w") as fh:
        fh.write("\n".join(O) + "\n")
    return path

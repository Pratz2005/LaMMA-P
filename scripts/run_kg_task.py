"""Run the KG-grounded pipeline on one MAT2Thor task and diff the result
against the knowledge graph.

The research claim this serves: the KG is built mechanically from AI2-THOR
metadata, so it is correct by construction. Every fact the LLM emits is
therefore either (a) entailed by the KG, or (b) something the LLM made up.
This script computes exactly that partition and attributes each invented fact
to the pipeline stage that first introduced it.

The pipeline itself is KGLAMP from kglamp_pipeline.py - this module adds only
the grounding checker on top, so what gets measured is the real pipeline rather
than a parallel reimplementation of it.

  python scripts/run_kg_task.py --dataset data/final_test/FloorPlan201.json \
      --task-index 0 --floor-plan 201 --fixture resources/kg_fixtures/FloorPlan201_metadata.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.append(".")

from scripts.kglamp_pipeline import (KGLAMP, load_task, resolve_robots,
                                     extract_pddl_block, DOMAIN_FILE)
from scripts.repair_pddl import repair as repair_pddl
from scripts.pipeline_trace import write_trace

from scripts.pddl_utils import (_section, parse_facts, parse_objects,
                                DOMAIN_PREDICATES, AFFORDANCES, DOMAIN_TYPES)


# --------------------------------------------------------------------------
# PDDL parsing
#
# load_task, resolve_robots and extract_pddl_block live in kglamp_pipeline so
# the pipeline and the checker cannot drift apart.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# ground truth from the KG
# --------------------------------------------------------------------------

def build_ground_truth(triplets: dict, robots: list) -> dict:
    """Translate KG triplets into the domain's vocabulary.

    The prompts instruct the model to encode relation/reach/property tuples
    using only the domain predicates, so we apply the same translation to the
    KG and compare like with like.
    """
    entities, at_location, closed, opened, robot_at = set(), set(), set(), set(), set()

    for r in robots:
        entities.add(r["name"].lower())

    for child, rel, parent in triplets["relation"]:
        entities.add(child.lower())
        entities.add(parent.lower())
        # (inside X Y) and (on X Y) both become (at-location X Y)
        at_location.add((child.lower(), parent.lower()))

    for subj, rel, loc in triplets["reach"]:
        entities.add(subj.lower())
        entities.add(str(loc).lower())
        if subj.lower() in {r["name"].lower() for r in robots}:
            robot_at.add((subj.lower(), str(loc).lower()))
        else:
            at_location.add((subj.lower(), str(loc).lower()))

    capabilities = set()
    vocabulary = set()      # capability/skill words - values, never entities
    openable = set()
    is_open = {}
    for subj, rel, val in triplets["property"]:
        entities.add(subj.lower())
        if rel == "has_capability":
            capabilities.add((subj.lower(), str(val).lower()))
            vocabulary.add(str(val).lower())
            if str(val) == "openable":
                openable.add(subj.lower())
        elif rel == "isOpen":
            is_open[subj.lower()] = bool(val)

    # An object is "closed" only if it is openable AND currently not open.
    # property_graph emits isOpen for EVERY object, so without the openable
    # filter a pen, a chair and the floor all count as closed containers.
    for name, flag in is_open.items():
        if name in openable:
            (opened if flag else closed).add(name)

    return {
        "entities": entities,
        "at_location": at_location,
        "robot_at": robot_at,
        "closed": closed,
        "opened": opened,
        "capabilities": capabilities,
        "vocabulary": vocabulary,
    }


# --------------------------------------------------------------------------
# the checker
# --------------------------------------------------------------------------

def _norm(sym: str) -> str:
    """Identity-insensitive form of a symbol, for near-miss detection."""
    return re.sub(r"[^a-z0-9]", "", sym.lower())


def _rename_of(sym: str, gt: dict):
    """If sym is a mangled spelling of a real entity, return that entity.

    The model rewrites CamelCase into snake_case - CounterTop_1 becomes
    Counter_top_1, GarbageCan_1 becomes Garbage_can_1. Those are not invented
    objects: it saw the real object and corrupted the identifier, which is a
    different (and more tractable) error than fabricating one.
    """
    n = _norm(sym)
    if not n:
        return None
    for e in gt["entities"]:
        if _norm(e) == n and e != sym:
            return e
    return None


def check_pddl(pddl: str, gt: dict, robots: list) -> list:
    """Classify every fact in the generated problem against the KG."""
    findings = []
    robot_names = {r["name"].lower() for r in robots}

    objects_txt = _section(pddl, "objects")
    init_txt = _section(pddl, "init")
    goal_txt = _section(pddl, "goal")

    declared = parse_objects(objects_txt)

    # parse_objects returns a dict, so repeats vanish silently - count the raw
    # token stream instead. Fast Downward rejects the whole file on a repeat
    # ("error: duplicate object 'book_1'"), so this is fatal, not cosmetic.
    _toks = objects_txt.replace("\n", " ").replace("(", " ").replace(")", " ").split()
    _names, _skip = [], False
    for _t in _toks:
        if _skip:
            _skip = False; continue
        if _t == "-":
            _skip = True; continue
        _names.append(_t.lower())
    for _n in sorted({x for x in _names if _names.count(x) > 1}):
        findings.append({
            "code": "DUPLICATE_DECLARATION", "where": ":objects", "fact": _n,
            "detail": f"{_n} is declared {_names.count(_n)} times under :objects - "
                      "Fast Downward rejects the file outright",
        })

    # Negation has to be caught textually: parse_facts only sees innermost
    # parens, so (not (holding r o)) yields the inner fact and never a "not".
    if re.search(r"\(\s*not\b", init_txt, re.IGNORECASE):
        findings.append({
            "code": "RULE_BREACH", "where": ":init",
            "fact": re.search(r"\(\s*not\b[^\n]*", init_txt, re.IGNORECASE).group(0).strip(),
            "detail": "negation in :init - forbidden by the prompt and meaningless under "
                      "the closed-world assumption",
        })

    # --- declared objects ---------------------------------------------------
    for sym, typ in declared.items():
        if typ and typ not in DOMAIN_TYPES:
            findings.append({
                "code": "INVENTED_TYPE", "where": ":objects", "fact": f"{sym} - {typ}",
                "detail": f"type '{typ}' is not declared in the domain (only {sorted(DOMAIN_TYPES)}). "
                          "Fast Downward will refuse this file.",
            })
        if sym not in gt["entities"]:
            real = _rename_of(sym, gt)
            if real:
                findings.append({
                    "code": "RENAMED_OBJECT", "where": ":objects", "fact": sym,
                    "detail": f"'{sym}' is a corrupted spelling of '{real}' - the object "
                              "exists but under this name nothing can bind to it",
                })
            else:
                findings.append({
                    "code": "INVENTED_OBJECT", "where": ":objects", "fact": sym,
                    "detail": "symbol does not exist anywhere in the knowledge graph",
                })

    # --- init ---------------------------------------------------------------
    for fact in parse_facts(init_txt):
        pred, args = fact[0], fact[1:]
        rendered = "(" + " ".join(fact) + ")"

        if pred == "not":
            findings.append({
                "code": "RULE_BREACH", "where": ":init", "fact": rendered,
                "detail": "negation in :init - forbidden by the prompt and meaningless "
                          "under the closed-world assumption",
            })
            continue

        if pred not in DOMAIN_PREDICATES:
            findings.append({
                "code": "INVENTED_PREDICATE", "where": ":init", "fact": rendered,
                "detail": f"'{pred}' is not a domain predicate",
            })
            continue

        if pred == "inaction":
            findings.append({
                "code": "RULE_BREACH", "where": ":init", "fact": rendered,
                "detail": "declaring (inaction ?r) makes every action inapplicable - "
                          "the problem becomes unsolvable",
            })
            continue

        unknown = [a for a in args if a not in gt["entities"]]
        if unknown:
            renamed = {u: _rename_of(u, gt) for u in unknown}
            if all(renamed.values()):
                findings.append({
                    "code": "RENAMED_OBJECT", "where": ":init", "fact": rendered,
                    "detail": "corrupted spellings of real objects: "
                              + ", ".join(f"{u} -> {r}" for u, r in renamed.items()),
                })
            else:
                findings.append({
                    "code": "INVENTED_OBJECT", "where": ":init", "fact": rendered,
                    "detail": f"references {[u for u in unknown if not renamed[u]]}, "
                              "absent from the knowledge graph",
                })
            continue

        if pred == "at-location" and len(args) == 2:
            if tuple(args) not in gt["at_location"]:
                findings.append({
                    "code": "UNSUPPORTED_FACT", "where": ":init", "fact": rendered,
                    "detail": f"KG has no containment/location edge {args[0]} -> {args[1]}",
                })
        elif pred == "at" and len(args) == 2:
            if tuple(args) not in gt["robot_at"]:
                findings.append({
                    "code": "UNSUPPORTED_FACT", "where": ":init", "fact": rendered,
                    "detail": f"KG does not place {args[0]} at {args[1]}",
                })
        elif pred == "object-open" and len(args) in (1, 2):
            if args[-1] in gt["closed"]:
                findings.append({
                    "code": "CONTRADICTION", "where": ":init", "fact": rendered,
                    "detail": f"KG says {args[1]} is CLOSED (isOpen=false)",
                })
        elif pred == "object-close" and len(args) in (1, 2):
            if args[-1] in gt["opened"]:
                findings.append({
                    "code": "CONTRADICTION", "where": ":init", "fact": rendered,
                    "detail": f"KG says {args[1]} is OPEN (isOpen=true)",
                })

    # --- symbols used but never declared -----------------------------------
    # The failure that actually sinks a generated problem: :init references
    # location_130 etc. while :objects declares only location_1. Fast Downward
    # rejects the file outright. Every symbol used anywhere must be declared.
    declared_names = set(declared)
    for where, text in ((":init", init_txt), (":goal", goal_txt)):
        reported = set()
        for fact in parse_facts(text):
            pred, fargs = fact[0], fact[1:]
            if pred in {"and", "or", "not"}:
                continue
            for a in fargs:
                if a in declared_names or a in reported or a in gt["vocabulary"]:
                    continue
                reported.add(a)
                findings.append({
                    "code": "UNDECLARED_OBJECT", "where": where, "fact": a,
                    "detail": f"used in {where} but never declared under :objects - "
                              "the planner cannot parse this problem",
                })

    # --- robots silently dropped -------------------------------------------
    for r in sorted(robot_names):
        if r not in declared_names:
            findings.append({
                "code": "MISSING_ROBOT", "where": ":objects", "fact": r,
                "detail": f"{r} is available for this task but was never declared - "
                          "the planner cannot assign any action to it",
            })

    # --- goal already asserted in the initial state -------------------------
    # The silent failure in its purest form: the model copies the goal literals
    # into :init, so the planner concludes the task is already done and returns
    # a ZERO-ACTION plan. Valid PDDL, "Solution found", robots never move.
    init_set = {tuple(f) for f in parse_facts(init_txt)}
    goal_lits = [f for f in parse_facts(goal_txt) if f[0] not in {"and", "or", "not"}]
    already = [f for f in goal_lits if tuple(f) in init_set]
    if goal_lits and len(already) == len(goal_lits):
        findings.append({
            "code": "GOAL_SATISFIED_IN_INIT", "where": ":init",
            "fact": "; ".join("(" + " ".join(f) + ")" for f in already),
            "detail": "every goal literal is already asserted in :init, so the planner "
                      "returns a zero-action plan and the task is never performed - "
                      "the goal state was hallucinated into the initial state",
        })
    elif already:
        findings.append({
            "code": "GOAL_SATISFIED_IN_INIT", "where": ":init",
            "fact": "; ".join("(" + " ".join(f) + ")" for f in already),
            "detail": f"{len(already)} of {len(goal_lits)} goal literals are already "
                      "asserted in :init, so the planner skips achieving them",
        })

    # --- missing affordances (the LaMMA-P "incomplete representation" case) --
    # The paper's example: a box encoded as closed, without recording that it is
    # openable, leaves the planner unable to retrieve its contents. Detect that
    # directly - a container asserted closed whose `openable` affordance was
    # dropped is permanently sealed.
    init_facts = parse_facts(init_txt)
    asserted = {(f[0], f[-1]) for f in init_facts if len(f) >= 2}
    closed_here = {f[-1] for f in init_facts if f[0] == "object-close"}
    for obj in sorted(closed_here):
        if (obj, "openable") in gt["capabilities"] and ("openable", obj) not in asserted:
            findings.append({
                "code": "MISSING_AFFORDANCE", "where": ":init",
                "fact": f"(object-close {obj})",
                "detail": f"{obj} is asserted closed, and the KG says it is openable, but "
                          f"(openable {obj}) was not emitted - OpenObject requires that "
                          "affordance, so the container can never be opened and its "
                          "contents are unreachable",
            })

    # Same failure for objects the goal actually needs to act on.
    goal_objs = {a for f in parse_facts(goal_txt) if f[0] not in {"and", "or", "not"}
                 for a in f[1:]}
    for obj in sorted(goal_objs):
        for pred, flag in AFFORDANCES.items():
            if (obj, flag) in gt["capabilities"] and (pred, obj) not in asserted:
                findings.append({
                    "code": "MISSING_AFFORDANCE", "where": ":init",
                    "fact": f"({pred} {obj})",
                    "detail": f"{obj} appears in the goal and the KG says it is {flag}, but "
                              f"({pred} {obj}) was not emitted - actions requiring that "
                              "affordance are inapplicable to it",
                })

    # --- dropped safety-critical facts -------------------------------------
    init_lower = init_txt.lower()
    for container in gt["closed"]:
        if container not in init_lower:
            continue        # container irrelevant to this problem, fine to omit
        # must be closed *for that container specifically*, not just any
        # object-close fact somewhere in :init
        if not re.search(rf"\(\s*object-close\s+(?:\S+\s+)?{re.escape(container)}\s*\)", init_lower):
            findings.append({
                "code": "DROPPED_CRITICAL_FACT", "where": ":init", "fact": container,
                "detail": f"KG says {container} is closed, but no (object-close {container}) "
                          "fact was emitted - pickup/put through it would be wrongly allowed",
            })

    # --- goal ---------------------------------------------------------------
    for fact in parse_facts(goal_txt):
        pred, args = fact[0], fact[1:]
        if pred in {"and", "not", "or"}:
            continue
        rendered = "(" + " ".join(fact) + ")"
        if pred not in DOMAIN_PREDICATES:
            findings.append({
                "code": "INVENTED_PREDICATE", "where": ":goal", "fact": rendered,
                "detail": f"'{pred}' is not a domain predicate",
            })
            continue
        unknown = [a for a in args if a not in gt["entities"]]
        if unknown:
            findings.append({
                "code": "INVENTED_OBJECT", "where": ":goal", "fact": rendered,
                "detail": f"references {unknown}, absent from the knowledge graph",
            })

    return findings


def check_stage_relations(text: str, stage: str, gt: dict) -> list:
    """Verify containment/support facts in an intermediate stage against the KG.

    Distinct from check_stage_text, which only catches invented *symbols*. The
    dangerous case uses entirely real symbols and still states something false:
    e.g. `(inside Watch_1 Drawer_1)` when the graph says
    `(on Watch_1 SideTable_3)` and Drawer_1 is empty. That is the goal state
    being echoed back as the initial state, and it is invisible to a
    symbol-existence check.
    """
    findings = []
    for fact in parse_facts(text):
        if len(fact) != 3 or fact[0] not in {"inside", "on", "at-location", "in"}:
            continue
        _, child, parent = fact
        if child not in gt["entities"] or parent not in gt["entities"]:
            continue        # invented symbols are check_stage_text's job
        if (child, parent) in gt["at_location"]:
            continue
        actual = sorted(p for c, p in gt["at_location"] if c == child)
        contents = sorted(c for c, p in gt["at_location"] if p == parent)
        findings.append({
            "code": "CONTRADICTION", "where": stage,
            "fact": "(" + " ".join(fact) + ")",
            "detail": (f"KG places {child} on/in "
                       f"{', '.join(actual) if actual else '<nothing>'}, not {parent}; "
                       f"{parent} actually holds "
                       f"{', '.join(contents) if contents else 'nothing'}"),
        })
    return findings


def check_stage_text(text: str, stage: str, gt: dict) -> list:
    """Look for invented object symbols in an intermediate stage's output.

    Catches hallucinations at the stage that introduced them, before they get
    laundered through two more prompts into the final PDDL.
    """
    findings = []
    seen = set()
    for fact in parse_facts(text):
        for arg in fact[1:]:
            if not re.match(r"^[a-z][\w\-]*_?\d*$", arg):
                continue
            if arg in {"true", "false", "and", "not", "or"} or arg.isdigit():
                continue
            # Capability/skill words (pickupable, GoToObject, ...) are VALUES in
            # (has_capability ?e ?skill), not entity names. Treating every
            # argument as an object flags the whole skill vocabulary as invented.
            if arg in gt["vocabulary"]:
                continue
            if arg not in gt["entities"] and arg not in seen:
                seen.add(arg)
                findings.append({
                    "code": "INVENTED_OBJECT", "where": stage, "fact": arg,
                    "detail": "symbol not present in the knowledge graph",
                })
    return findings


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="data/final_test/FloorPlan201.json")
    ap.add_argument("--task-index", type=int, default=0)
    ap.add_argument("--floor-plan", type=int, default=201)
    ap.add_argument("--fixture", default=None,
                    help="cached metadata JSON; captured from AI2-THOR if absent")
    ap.add_argument("--fixture-dir", default="resources/kg_fixtures")
    ap.add_argument("--base-url", default=os.environ.get("KGLAMP_LLM_BASE_URL",
                                                         "http://localhost:8000/v1"))
    ap.add_argument("--model", default=os.environ.get("KGLAMP_MODEL",
                                                      "Qwen/Qwen2-7B-Instruct"))
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    task_row = load_task(args.dataset, args.task_index)
    task = task_row["task"]
    robots = resolve_robots(task_row["robot list"])

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    tier = ("vague" if "vague" in args.dataset else
            "complex" if "pddl" in args.dataset else "easy")
    runs_root = os.environ.get("KGLAMP_RUNS_DIR", "runs")
    out_dir = args.out_dir or os.path.join(
        runs_root, f"FP{args.floor_plan}_t{args.task_index}_{tier}_{run_id}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"task      : {task}")
    print(f"robots    : {[(r['name'], r['dataset_id']) for r in robots]}")
    print(f"out       : {out_dir}")

    # --- run the real pipeline ---------------------------------------------
    kglamp = KGLAMP(
        floor_no=args.floor_plan, robots=robots, fixture=args.fixture,
        base_url=args.base_url, model=args.model, log_dir=out_dir,
    )

    pddl, plan_output, parse_error = None, "", None
    try:
        pddl, plan_output = kglamp.run(task)
    except ValueError as exc:
        # "no (define ...) block" / "unbalanced parentheses" - a failure to
        # produce usable PDDL at all. That is itself a result worth recording,
        # not a crash: report it and carry on checking the earlier stages.
        parse_error = str(exc)
        print(f"\n!! final stage produced no usable PDDL: {parse_error}")

    triplets = kglamp.triplets
    gt = build_ground_truth(triplets, robots)
    print(f"\nKG        : {len(triplets['property'])} property, "
          f"{len(triplets['relation'])} relation, {len(triplets['reach'])} reach triplets; "
          f"{len(gt['entities'])} entities")

    # --- check --------------------------------------------------------------
    findings = []
    for stage, key in [("1_goal", "goal"), ("2_relation", "relation"),
                       ("3_property", "property"), ("4_reach", "reach")]:
        if key not in kglamp.stages:
            continue
        findings.extend(check_stage_text(kglamp.stages[key], stage, gt))
        # The goal stage legitimately describes a state that is NOT true yet,
        # so contradiction-checking it would flag the goal for being a goal.
        if key != "goal":
            findings.extend(check_stage_relations(kglamp.stages[key], stage, gt))

    if parse_error:
        findings.append({
            "code": "UNPARSEABLE_PDDL", "where": "5_pddl", "fact": parse_error,
            "detail": "final stage did not emit a usable PDDL problem; see 5_pddl.out.txt",
        })
    else:
        with open(os.path.join(out_dir, "problem.pddl"), "w") as f:
            f.write(pddl)
        findings.extend(check_pddl(pddl, gt, robots))

    # --- second planning pass on a syntax-repaired copy ---------------------
    # Syntax errors and semantic errors mask each other: a duplicate declaration
    # makes the translator abort, so the planner never reaches the content error
    # underneath. Repair ONLY syntax - never affordances, fact values or the
    # goal - and plan again, so a hallucination that does not break parsing
    # still produces a plan we can inspect.
    repair_changes, plan_repaired = [], ""
    if pddl and "Solution found" not in (plan_output or ""):
        try:
            fixed, repair_changes = repair_pddl(pddl, [r["name"] for r in robots])
            rp = os.path.join(out_dir, "problem_repaired.pddl")
            with open(rp, "w") as f:
                f.write(fixed + "\n")
            kglamp.planner.run_plan(DOMAIN_FILE, rp)
            plan_repaired = kglamp.file_processor.read_file(
                rp.replace(".pddl", "_plan.txt"))
            with open(os.path.join(out_dir, "plan_repaired.txt"), "w") as f:
                f.write(plan_repaired)
            print(f"\n[repair] {len(repair_changes)} syntax fix(es), re-planned -> "
                  + ("SOLVED" if "Solution found" in plan_repaired else "still unsolvable"))
        except Exception as exc:
            print(f"[repair] failed: {exc}")

    # --- does the plan actually accomplish the task? ------------------------
    # A solvable plan is not a correct plan. Compare the actions against the
    # dataset's ground-truth object_states: a plan the planner accepts can still
    # leave the task undone, which is the silent-failure case that matters.
    plan_actions_out = []
    effective_plan = plan_repaired if "Solution found" in plan_repaired else (plan_output or "")
    if "Solution found" in effective_plan:
        plan_src = plan_repaired if "Solution found" in plan_repaired else plan_output
        pf = os.path.join(out_dir, "problem_repaired_plan.txt") \
            if "Solution found" in plan_repaired else None
        # The ACTIONS live in the .plan file; plan_src is only search statistics.
        plan_file = os.path.join(out_dir, "problem_repaired.plan") \
            if "Solution found" in plan_repaired else None
        plan_text = ""
        if plan_file and os.path.exists(plan_file):
            plan_text = open(plan_file).read()
        elif os.path.exists("sas_plan"):
            plan_text = open("sas_plan").read()
        acts = re.findall(r"^\(([a-z-]+)([^)]*)\)", plan_text, re.MULTILINE)
        actions = [(a.strip().lower(), b.split()) for a, b in acts]
        with open(os.path.join(out_dir, "plan_actions.txt"), "w") as f:
            f.write("\n".join(f"({a} {' '.join(b)})" for a, b in actions))
        plan_actions_out = actions

        for spec in (task_row.get("object_states") or []):
            name = str(spec.get("name", "")).lower()
            want_state = (spec.get("state") or "").upper()
            if want_state == "OPENED":
                if not any(a == "openobject" and any(x.startswith(name) for x in b)
                           for a, b in actions):
                    findings.append({
                        "code": "TASK_NOT_ACHIEVED", "where": "plan",
                        "fact": f"{spec['name']} must end OPENED",
                        "detail": "the plan is accepted by the planner but contains no "
                                  f"OpenObject on {spec['name']} - executing it leaves the "
                                  "task unfinished",
                    })
            for item in (spec.get("contains") or []):
                if not any(a == "putobject" and any(x.startswith(item.lower()) for x in b)
                           for a, b in actions):
                    findings.append({
                        "code": "TASK_NOT_ACHIEVED", "where": "plan",
                        "fact": f"{item} must end in/on {spec['name']}",
                        "detail": "the plan is accepted by the planner but never puts "
                                  f"{item} on {spec['name']}",
                    })

        # actions serving no part of the task at all
        task_objs = {str(s.get("name", "")).lower() for s in (task_row.get("object_states") or [])}
        task_objs |= {i.lower() for s in (task_row.get("object_states") or [])
                      for i in (s.get("contains") or [])}
        for a, b in actions:
            if a in ("gotoobject",):
                continue
            targets = [x for x in b if not x.startswith("robot")]
            if targets and not any(t.startswith(tuple(task_objs)) for t in targets):
                findings.append({
                    "code": "HALLUCINATED_ACTION", "where": "plan",
                    "fact": f"({a} {' '.join(b)})",
                    "detail": f"the plan acts on {targets} which appears nowhere in the "
                              "task or its ground-truth object_states",
                })

    if plan_output:
        with open(os.path.join(out_dir, "plan.txt"), "w") as f:
            f.write(plan_output)
        if "Solution found" not in plan_output:
            # Two very different failures wear the same "no plan" face:
            # the translator refusing to parse the file, and the search proving
            # no plan exists. Conflating them hides which stage went wrong.
            m = re.search(r"translate exit code:\s*(\d+)", plan_output)
            if m and m.group(1) != "0":
                reason = re.findall(r"^error:.*$", plan_output, re.MULTILINE)
                findings.append({
                    "code": "INVALID_PDDL", "where": "planner",
                    "fact": "; ".join(reason) or f"translate exit {m.group(1)}",
                    "detail": "Fast Downward's translator rejected the problem file - "
                              "it is not valid PDDL, so no plan was even attempted",
                })
            else:
                findings.append({
                    "code": "UNSOLVABLE", "where": "planner", "fact": "no plan",
                    "detail": "the problem parses but no plan exists - the initial state "
                              "or goal is semantically wrong (e.g. a required affordance "
                              "was omitted, making the needed action inapplicable)",
                })

    report = {
        "task": task, "dataset": args.dataset, "task_index": args.task_index,
        "floor_plan": args.floor_plan, "model": kglamp.llm.model, "temperature": 0,
        "robots": [{"name": r["name"], "dataset_id": r["dataset_id"]} for r in robots],
        "kg_entity_count": len(gt["entities"]),
        "ground_truth_object_states": task_row.get("object_states"),
        "planner_ran": bool(plan_output),
        "repair_changes": repair_changes,
        "solved_after_repair": "Solution found" in plan_repaired,
        "findings": findings,
    }
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)

    # --- print --------------------------------------------------------------
    lines = []
    lines.append("=" * 70)
    lines.append(f"HALLUCINATION REPORT  -  {len(findings)} finding(s)")
    lines.append("=" * 70)
    if not findings:
        lines.append("none: every generated fact is entailed by the knowledge graph.")
    else:
        by_code = {}
        for f_ in findings:
            by_code.setdefault(f_["code"], []).append(f_)
        for code, items in sorted(by_code.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"\n{code}  ({len(items)})")
            for it in items:
                lines.append(f"  [{it['where']}] {it['fact']}")
                lines.append(f"      -> {it['detail']}")
    report_text = "\n".join(lines)
    print("\n" + report_text)

    # --- one readable file with the whole run -------------------------------
    # Everything in one place: the graph facts the model was given, what each
    # stage returned, the problem it produced, the planner's verdict, and the
    # findings. Opening five files to reconstruct a run is how detail gets lost.
    def block(title, body):
        return f"\n{'=' * 70}\n{title}\n{'=' * 70}\n{body}\n"

    # The property graph is where affordances live, so it has to be in the log
    # verbatim - a count is useless when the question is "was the model told
    # this object is openable?". False states are omitted: property_graph emits
    # every state flag for every object, so ~90% of them are noise, and
    # property_prompt already drops them (isOpen=False is kept, as isClosed).
    prop_caps = [(a, b) for a, r, b in triplets["property"] if r == "has_capability"]
    prop_state = [(a, r, b) for a, r, b in triplets["property"]
                  if r != "has_capability" and (b or r == "isOpen")]

    kg_summary = "\n".join([
        f"property triplets : {len(triplets['property'])} "
        f"({len(prop_caps)} capabilities, {len(prop_state)} meaningful states)",
        f"relation triplets : {len(triplets['relation'])}",
        f"reach triplets    : {len(triplets['reach'])}",
        f"distinct entities : {len(gt['entities'])}",
        "",
        "capabilities / affordances as ground truth:",
        *[f"  (has_capability {a} {b})" for a, b in prop_caps],
        "",
        "object states as ground truth (isOpen False is rendered isClosed by the prompt):",
        *[f"  ({r} {a} {b})" for a, r, b in prop_state],
        "",
        "relation edges (containment / support) as ground truth:",
        *[f"  ({r} {a} {b})" for a, r, b in triplets["relation"]],
        "",
        "reach edges:",
        *[f"  ({r} {a} {b})" for a, r, b in triplets["reach"]],
    ])

    with open(os.path.join(out_dir, "run_log.txt"), "w") as f:
        f.write(f"task       : {task}\n")
        f.write(f"dataset    : {args.dataset} [index {args.task_index}]\n")
        f.write(f"floor plan : FloorPlan{args.floor_plan}\n")
        f.write(f"model      : {kglamp.llm.model}  (temperature 0, seed 0)\n")
        f.write(f"robots     : {[(r['name'], r['dataset_id']) for r in robots]}\n")
        f.write(f"ground truth object_states: {task_row.get('object_states')}\n")
        f.write(block("KNOWLEDGE GRAPH (ground truth given to the model)", kg_summary))
        for stage, key in [("1_goal", "goal"), ("2_relation", "relation"),
                           ("3_property", "property"), ("4_reach", "reach"),
                           ("5_pddl", "pddl_raw")]:
            if key in kglamp.stages:
                f.write(block(f"STAGE {stage} - raw model output", kglamp.stages[key]))
        f.write(block("GENERATED PROBLEM PDDL",
                      pddl if pddl else f"<none: {parse_error}>"))
        f.write(block("FAST DOWNWARD PLAN OUTPUT (model output as-is)",
                      plan_output if plan_output else "<planner did not run>"))
        if repair_changes:
            f.write(block(f"SYNTAX REPAIR ({len(repair_changes)} change(s); "
                          "affordances / goal / fact values untouched)",
                          "\n".join("  - " + c for c in repair_changes)))
            f.write(block("FAST DOWNWARD PLAN OUTPUT (after syntax repair)",
                          plan_repaired or "<no output>"))
        f.write(block("FINDINGS", report_text))

    write_trace(
        os.path.join(out_dir, "pipeline_trace.txt"),
        task_row, args, robots, triplets, gt, kglamp.stages,
        pddl, plan_actions_out,
        "Solution found" in (plan_repaired or plan_output or ""),
        findings, repair_changes, kglamp.llm.model, kglamp.out_path)

    print(f"\ntrace        : {out_dir}/pipeline_trace.txt")
    print(f"full run log : {out_dir}/run_log.txt")
    print(f"problem pddl : {out_dir}/problem.pddl")
    print(f"plan output  : {out_dir}/plan.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())

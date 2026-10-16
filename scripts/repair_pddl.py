"""Mechanically repair SYNTAX errors in a generated PDDL problem, without
touching its semantic content.

Motivation: the model makes two very different kinds of error, and they get
tangled together. Syntactic errors (duplicate declarations, a type the domain
does not have, a predicate that does not exist) stop Fast Downward from parsing
the file at all, so the semantic error underneath is never reached. To show that
a dropped affordance is what makes a task impossible, the syntax noise has to be
removed first - otherwise the planner fails for the wrong reason.

WHAT THIS CHANGES (syntax only):
  * duplicate :objects declarations      -> declared once
  * a type not in the domain             -> coerced to `object`
  * predicates that exist nowhere        -> dropped, including (inside X Y)
                                            and (on X Y): translating relation
                                            tuples into domain predicates is
                                            stage 5's job, and doing it here
                                            silently repaired a model error
  * symbols used but never declared      -> declared as `object`
  * robots in the task but not declared  -> declared as `robot`

WHAT THIS DELIBERATELY DOES NOT CHANGE:
  * affordances. If the model omitted (openable X), it stays omitted. That
    omission is the finding; repairing it would destroy the experiment.
  * any fact's truth value.
  * the goal, with one declared exception: a world-state literal carrying a
    spurious leading robot argument, e.g. (switch-off robot1 lightswitch_1)
    against a predicate of arity 1, is an arity error that aborts Fast
    Downward's parser before any semantic error can surface. The stray
    argument is dropped and the edit is reported like any other.

Every edit is reported, so the diff between input and output is auditable.
"""

import argparse
import re
import sys

sys.path.append(".")
from scripts.pddl_utils import (_section, parse_facts, parse_objects,
                                DOMAIN_PREDICATES, DOMAIN_TYPES)

# World-state predicates. These take a single object argument: they describe the
# object, not the robot that acted on it. A leading robot argument is the common
# model error (the LaMMA-P domain this repo inherited indexed them by robot), and
# it aborts Fast Downward's parser on an arity mismatch before any semantic error
# can surface, so the stray argument is stripped rather than the run being lost.
OBJECT_STATE_PREDICATES = {
    "switch-on", "switch-off", "object-open", "object-close", "break", "cleaned",
}


def strip_robot_arg(fact: list, robot_names: list, changes: list, where: str) -> list:
    """(switch-off robot1 X) -> (switch-off X). Arity repair, not a semantic edit."""
    if (fact[0] in OBJECT_STATE_PREDICATES and len(fact) == 3
            and fact[1] in robot_names):
        changes.append(f"stripped robot argument in {where}: ({' '.join(fact)}) -> "
                       f"({fact[0]} {fact[2]}) - predicate takes one object argument")
        return [fact[0], fact[2]]
    return fact


def repair(pddl: str, robot_names: list) -> tuple:
    changes = []
    objects_txt = _section(pddl, "objects")
    init_txt = _section(pddl, "init")
    goal_txt = _section(pddl, "goal")
    m = re.search(r"\(define\s+\(problem\s+([\w-]+)\)", pddl)
    problem_name = m.group(1) if m else "repaired"
    m = re.search(r"\(:domain\s+([\w-]+)\)", pddl)
    domain_name = m.group(1) if m else "robot3"

    # ---- :objects — dedupe, coerce unknown types --------------------------
    declared = parse_objects(objects_txt)          # dict collapses duplicates
    raw_names = []
    toks = objects_txt.replace("\n", " ").replace("(", " ").replace(")", " ").split()
    skip = False
    for t in toks:
        if skip:
            skip = False; continue
        if t == "-":
            skip = True; continue
        raw_names.append(t.lower())
    for n in sorted({x for x in raw_names if raw_names.count(x) > 1}):
        changes.append(f"deduped :objects declaration of {n} "
                       f"({raw_names.count(n)} -> 1)")

    typed = {}
    for name, typ in declared.items():
        if typ not in DOMAIN_TYPES:
            changes.append(f"coerced type of {name}: '{typ}' -> 'object' "
                           "(type not declared in the domain)")
            typ = "object"
        typed[name] = typ
    for r in robot_names:
        if r not in typed:
            changes.append(f"declared missing robot {r}")
        typed[r] = "robot"

    # ---- :init — translate aliases, drop unknown predicates ---------------
    kept = []
    for fact in parse_facts(init_txt):
        pred, args = fact[0], fact[1:]
        if pred == "not":
            changes.append(f"dropped negation in :init: ({' '.join(fact)})")
            continue
        if pred not in DOMAIN_PREDICATES:
            changes.append(f"dropped unknown predicate: ({' '.join(fact)})")
            continue
        if pred == "inaction":
            changes.append(f"dropped (inaction ...) - makes every action inapplicable")
            continue
        kept.append(strip_robot_arg([pred] + args, robot_names, changes, ":init"))

    # ---- goal: strip spurious robot arguments -----------------------------
    goal_facts = []
    for f in parse_facts(goal_txt):
        if f[0] in {"and", "or", "not"}:
            continue
        f = strip_robot_arg(f, robot_names, changes, ":goal")
        goal_facts.append(f)

    # ---- declare anything used but undeclared -----------------------------
    used = {a for f in kept for a in f[1:]}
    used |= {a for f in goal_facts for a in f[1:]}
    for sym in sorted(used - set(typed)):
        typed[sym] = "robot" if sym in robot_names else "object"
        changes.append(f"declared undeclared symbol {sym} as {typed[sym]}")

    # ---- emit --------------------------------------------------------------
    robots = sorted(n for n, t in typed.items() if t == "robot")
    objs = sorted(n for n, t in typed.items() if t == "object")
    out = [f"(define (problem {problem_name})", f"  (:domain {domain_name})", "  (:objects"]
    out += [f"    {' '.join(robots)} - robot"] if robots else []
    for i in range(0, len(objs), 6):
        out.append("    " + " ".join(objs[i:i + 6]) + " - object")
    out.append("  )")
    out.append("  (:init")
    out += [f"    ({' '.join(f)})" for f in kept]
    out.append("  )")
    out.append("  (:goal")
    out.append("    (and")
    for f in goal_facts:
        out.append(f"      ({' '.join(f)})")
    out.append("    )")
    out.append("  )")
    out.append(")")
    return "\n".join(out), changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--robots", default="robot1,robot2")
    ap.add_argument("--goal", default=None,
                    help="replace the goal, e.g. '(object-open robot2 Book_1)'. "
                         "Use only with an explicit justification - it changes the "
                         "experiment.")
    ap.add_argument("--add-fact", action="append", default=[],
                    help="inject a fact into :init. Used ONLY to build the "
                         "counterfactual, never to fix the model's output.")
    args = ap.parse_args()

    src = open(args.problem).read()
    if args.goal:
        src = re.sub(r"\(:goal.*\)\s*\)\s*$", f"(:goal (and {args.goal})))", src,
                     flags=re.DOTALL)

    fixed, changes = repair(src, args.robots.split(","))

    for fact in args.add_fact:
        fixed = fixed.replace("  (:init\n", f"  (:init\n    {fact}\n", 1)
        changes.append(f"INJECTED {fact}  <- counterfactual, not a repair")

    open(args.out, "w").write(fixed + "\n")
    print(f"{args.problem} -> {args.out}")
    print(f"{len(changes)} change(s):")
    for c in changes:
        print("  -", c)


if __name__ == "__main__":
    main()

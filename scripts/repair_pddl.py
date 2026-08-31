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
  * (on X Y) / (inside X Y) in :init     -> (at-location X Y), per the prompt's
                                            own translation rule
  * predicates that exist nowhere        -> dropped
  * symbols used but never declared      -> declared as `object`
  * robots in the task but not declared  -> declared as `robot`

WHAT THIS DELIBERATELY DOES NOT CHANGE:
  * affordances. If the model omitted (openable X), it stays omitted. That
    omission is the finding; repairing it would destroy the experiment.
  * any fact's truth value, or the goal.

Every edit is reported, so the diff between input and output is auditable.
"""

import argparse
import re
import sys

sys.path.append(".")
from scripts.pddl_utils import (_section, parse_facts, parse_objects,
                                DOMAIN_PREDICATES, DOMAIN_TYPES)

# The prompts tell the model that relation tuples become at-location facts;
# apply that same rule rather than inventing a new one here.
RELATION_ALIASES = {"on": "at-location", "inside": "at-location", "in": "at-location"}


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
        if pred in RELATION_ALIASES:
            new = RELATION_ALIASES[pred]
            changes.append(f"translated ({pred} {' '.join(args)}) -> "
                           f"({new} {' '.join(args)})")
            pred = new
        if pred not in DOMAIN_PREDICATES:
            changes.append(f"dropped unknown predicate: ({' '.join(fact)})")
            continue
        if pred == "inaction":
            changes.append(f"dropped (inaction ...) - makes every action inapplicable")
            continue
        kept.append([pred] + args)

    # ---- declare anything used but undeclared -----------------------------
    used = {a for f in kept for a in f[1:]}
    used |= {a for f in parse_facts(goal_txt) if f[0] not in {"and", "or", "not"}
             for a in f[1:]}
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
    for f in parse_facts(goal_txt):
        if f[0] in {"and", "or", "not"}:
            continue
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

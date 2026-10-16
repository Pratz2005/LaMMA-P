"""Safety-DAG: derive ordering constraints from the knowledge graph, check a
plan against them, and report what is missing.

The knowledge graph already contains everything needed to know that some
actions must precede others. Putting an object into a container that is
openable and currently closed requires opening it first. That is a rule over
graph facts, not a judgement, so it does not need a language model - and it
holds whether or not the model remembered to emit the facts, because it is
evaluated against the graph rather than against the generated PDDL.

That is the point. When the property stage drops (isClosed Drawer_1), the
planner believes the drawer is open and emits a plan with no OpenObject. Fast
Downward reports success, so KGLAMP's replanning loop - which is gated on an
error signal - never fires. The DAG check runs regardless of planner success
and catches it.

Vocabulary matters and is handled structurally. A violation has to name the
missing fact in the vocabulary of whichever stage is being regenerated:

    property stage   (isClosed Drawer_1)      <- rendered by property_prompt
    PDDL :init       (object-close drawer_1)  <- domain predicate

The property form is produced by calling property_prompt.format_property_triplet
on the graph triplet itself, so the feedback and the prompt cannot drift apart.
Writing that string by hand is how you end up telling the model to emit
(has_state Drawer_1 closed), which no stage accepts and repair silently drops.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import namedtuple

sys.path.append(".")
from scripts.property_prompt import format_property_triplet

# before/after are ("Verb", arg...) tuples matched against plan actions.
# kind decides how the edge is checked:
#   "order"     before must appear in the plan, and before after
#   "presence"  before must appear at all (after is None)
#   "init_fact" atom_init must be present in the problem file's :init
Edge = namedtuple("Edge",
                  "before after rule evidence atom_property atom_init kind")
Violation = namedtuple("Violation", "edge reason before_idx after_idx")

# plan actions as Fast Downward emits them, e.g. (putobject robot1 watch_1 drawer_1)
VERB_TO_ACTION = {"Open": "openobject", "Close": "closeobject",
                  "Put": "putobject", "Pickup": "pickupobject",
                  "SwitchOn": "switchon", "SwitchOff": "switchoff"}


# --------------------------------------------------------------------- graph --
Graph = namedtuple("Graph", "openable closed toggled inside triplet")


def load_graph(run_dir):
    """Everything the rules read, from the knowledge graph only.

    triplet maps (lowercased entity, flag) -> the original triplet, so an atom
    can be rendered with property_prompt's own formatter and keep its casing.
    """
    tri = json.load(open(os.path.join(run_dir, "triplets.json")))
    prop = tri.get("property", []) if isinstance(tri, dict) else tri
    rel_ = tri.get("relation", []) if isinstance(tri, dict) else []
    openable, closed, toggled, triplet = set(), set(), set(), {}
    for t in prop:
        if not (isinstance(t, (list, tuple)) and len(t) == 3):
            continue
        subj, rel, val = t
        s = str(subj).lower()
        if rel == "has_capability" and val == "openable":
            openable.add(s); triplet[(s, "openable")] = (subj, rel, val)
        elif rel == "isOpen" and val is False:
            closed.add(s); triplet[(s, "closed")] = (subj, rel, val)
        elif rel == "isToggled" and val is True:
            toggled.add(s); triplet[(s, "toggled")] = (subj, rel, val)
    inside = {(str(a).lower(), str(b).lower())
              for a, r, b in (t for t in rel_ if len(t) == 3) if r == "inside"}
    return Graph(openable, closed, toggled, inside, triplet)


Goals = namedtuple("Goals", "put open_ switch_on switch_off")


def load_problem(run_dir):
    for name in ("problem_repaired.pddl", "problem.pddl"):
        p = os.path.join(run_dir, name)
        if os.path.exists(p):
            return open(p).read().lower()
    return ""


def load_goal(run_dir):
    """Goal literals, split by what they demand. Never reads ground truth."""
    txt = load_problem(run_dir)
    g = txt[txt.find("(:goal"):] if "(:goal" in txt else ""
    one = lambda pred: re.findall(r"\(" + pred + r"\s+([^\s()]+)\)", g)
    return Goals(
        put=re.findall(r"\(at-location\s+([^\s()]+)\s+([^\s()]+)\)", g),
        open_=one("object-open"),
        switch_on=one("switch-on"),
        switch_off=one("switch-off"))


def load_plan(run_dir):
    # plan.plan is what demo_dag_loop writes; plan_final.txt is what
    # replan_runs writes; the rest are the pipeline's own names.
    for name in ("plan_final.txt", "plan.plan", "plan_actions.txt",
                 "problem_repaired.plan", "sas_plan"):
        p = os.path.join(run_dir, name)
        if os.path.exists(p):
            return [l.strip().lower() for l in open(p)
                    if l.strip().startswith("(")]
    return []


# ---------------------------------------------------------------------- rules --
def _closed_atoms(g, Y):
    """The two vocabularies for 'Y is closed', rendered from the graph itself."""
    return format_property_triplet(g.triplet[(Y, "closed")]), "(object-close %s)" % Y


def rule_open_before_put(goals, g):
    """Put X into Y, where Y is openable and closed -> Open(Y) < Put(X, Y).

    PutObject's precondition is (not (object-close ?location)). Under the closed
    world assumption a missing fact is false, so omitting 'Y is closed' silently
    GRANTS permission and the open step is never planned. Silent failure.
    """
    out = []
    for X, Y in goals.put:
        if Y not in g.openable or Y not in g.closed:
            continue
        ap, ai = _closed_atoms(g, Y)
        out.append(Edge(("Open", Y), ("Put", X, Y), "open_before_put",
                        ["(%s, has_capability, openable)" % Y, "(%s, isOpen, False)" % Y],
                        ap, ai, "order"))
    return out


def rule_open_before_pickup(goals, g):
    """X starts inside a closed openable Z -> Open(Z) < Pickup(X).

    The case KGLAMP names in IV-C: a box encoded as closed without recording
    that it is openable leaves the planner unable to retrieve its contents.
    """
    out = []
    wanted = {X for X, _ in goals.put}
    for X, Z in g.inside:
        if X not in wanted or Z not in g.openable or Z not in g.closed:
            continue
        ap, ai = _closed_atoms(g, Z)
        out.append(Edge(("Open", Z), ("Pickup", X), "open_before_pickup",
                        ["(%s, inside, %s)" % (X, Z), "(%s, isOpen, False)" % Z],
                        ap, ai, "order"))
    return out


def rule_openable_for_open_goal(goals, g):
    """Goal demands Y be open, and the graph says Y is openable.

    OpenObject requires (openable ?object) POSITIVELY, so a dropped affordance
    blocks the action outright: no plan at all. Loud rather than silent, but
    repairable from the graph exactly the same way.
    """
    out = []
    for Y in goals.open_:
        if Y not in g.openable:
            continue
        out.append(Edge(("Open", Y), None, "openable_for_open_goal",
                        ["(%s, has_capability, openable)" % Y],
                        format_property_triplet(g.triplet[(Y, "openable")]),
                        "(openable %s)" % Y, "init_fact"))
    return out


def rule_switch_off_when_on(goals, g):
    """Goal wants Y off and the graph says Y is currently on -> plan must switch it.

    No precondition guards this one. It fails when the model asserts the goal
    itself into :init - 'the light is already off' - so the goal holds at time
    zero, the planner returns a zero-action plan and the light stays on.
    Injecting the true state makes the goal false again and forces the action.
    """
    out = []
    for Y in goals.switch_off:
        if Y not in g.toggled:
            continue
        out.append(Edge(("SwitchOff", Y), None, "switch_off_when_on",
                        ["(%s, isToggled, True)" % Y],
                        format_property_triplet(g.triplet[(Y, "toggled")]),
                        "(switch-on %s)" % Y, "presence"))
    return out


RULES = [rule_open_before_put, rule_open_before_pickup,
         rule_openable_for_open_goal, rule_switch_off_when_on]


def derive_dag(run_dir):
    g, goals = load_graph(run_dir), load_goal(run_dir)
    edges = []
    for rule in RULES:
        edges.extend(rule(goals, g))
    return edges


# ---------------------------------------------------------------------- check --
def _find(plan, spec):
    """Index of the first plan action matching ("Verb", arg...), else -1."""
    verb, args = spec[0], list(spec[1:])
    action = VERB_TO_ACTION[verb]
    for i, step in enumerate(plan):
        if not step.startswith("(" + action):
            continue
        toks = step.strip("()").split()[1:]          # drop the action name
        if all(a in toks for a in args):
            return i
    return -1


def check_plan(edges, plan, pddl=""):
    """Violations, by edge kind.

    order      the successor is planned but its predecessor is missing, or runs
               after it. An edge with neither endpoint present is NOT counted -
               the plan simply does not attempt that goal, which is a different
               failure and is reported separately as not_attempted.
    presence   the action must appear at all; its absence means the goal was
               satisfied in :init instead of being achieved.
    init_fact  the atom must appear in the problem file's :init.
    """
    out = []
    for e in edges:
        if e.kind == "init_fact":
            pat = re.escape(e.atom_init.lower()).replace(r"\ ", r"\s+")
            if pddl and not re.search(pat, pddl.lower()):
                out.append(Violation(e, "missing_init_fact", -1, -1))
            continue
        if e.kind == "presence":
            if _find(plan, e.before) < 0:
                out.append(Violation(e, "required_action_absent", -1, -1))
            continue
        i_after = _find(plan, e.after)
        if i_after < 0:
            continue
        i_before = _find(plan, e.before)
        if i_before < 0:
            out.append(Violation(e, "missing_predecessor", -1, i_after))
        elif i_before > i_after:
            out.append(Violation(e, "wrong_order", i_before, i_after))
    return out


def feedback(v, stage="property"):
    """Structured feedback naming the atom in the target stage's vocabulary."""
    e = v.edge
    atom = e.atom_property if stage == "property" else e.atom_init
    fmt = lambda s: f"{s[0]}({', '.join(s[1:])})" if s else "(anywhere in the plan)"
    return (f"  violation: {v.reason}\n"
            f"  required:  {fmt(e.before)}\n"
            f"  before:    {fmt(e.after)}\n"
            f"  evidence:  " + "\n             ".join(e.evidence) + "\n"
            f"  missing fact, in this stage's vocabulary: {atom}")


# ------------------------------------------------------------------------ cli --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="run directories, or globs like 'runs_2/FP*'")
    ap.add_argument("--stage", default="property", choices=["property", "init"])
    ap.add_argument("--quiet", action="store_true", help="only show violations")
    args = ap.parse_args()

    dirs = []
    for r in args.runs:
        dirs.extend(sorted(glob.glob(r)) if any(c in r for c in "*?[") else [r])

    total_edges = total_viol = 0
    for d in dirs:
        if not os.path.exists(os.path.join(d, "triplets.json")):
            continue
        edges = derive_dag(d)
        plan = load_plan(d)
        viols = check_plan(edges, plan, load_problem(d))
        total_edges += len(edges)
        total_viol += len(viols)
        if args.quiet and not viols:
            continue
        print(f"\n=== {d}")
        print(f"    plan: {len(plan)} actions | DAG edges: {len(edges)} | "
              f"violations: {len(viols)}")
        for e in edges:
            mark = "VIOLATED" if any(v.edge is e for v in viols) else "ok"
            fmt = lambda s: f"{s[0]}({', '.join(s[1:])})" if s else "*"
            print(f"      [{mark:8s}] {fmt(e.before)} < {fmt(e.after)}   ({e.rule})")
        for v in viols:
            print(feedback(v, args.stage))
    print(f"\ntotal: {total_edges} edges, {total_viol} violations "
          f"across {len(dirs)} run(s)")


if __name__ == "__main__":
    main()

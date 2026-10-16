"""Repair a DAG violation by restoring the missing fact to (:init ...).

    pixi run python scripts/dag_inject.py runs_dagdemo
    pixi run python scripts/dag_inject.py runs_dagdemo --llm

The Safety-DAG derives the missing ordering constraint from the knowledge
graph, so it already holds the exact ground atom the problem file lacks. Asking
a model to re-emit that atom is one option; writing it in directly is the other,
and it cannot fail. This runs either.

    detect -> get the atom -> inject into (:init ...) -> replan -> re-check

By default the atom comes from edge.atom_init: no LLM call, no prompt, no
sampling, and the only thing added to the problem file is a fact the graph
already asserts, in the domain's own vocabulary. With --llm the same atom is
asked of the model instead and screened before it lands - see
scripts/dag_llm_init.py for the prompt and the three screening passes.

Either way every insertion is printed, and the goal, the objects and every other
fact are untouched.

Use --dry-run to see what would be inserted without writing anything, and --llm
to source the atoms from the model instead (scripts/dag_llm_init.py) - same
detection, same injection, same replan, but the fact is asked for rather than
written in, and screened against the domain and the graph before it lands.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.append(".")
from scripts.safety_dag import (derive_dag, check_plan, load_plan,
                                load_problem, load_graph, feedback)

# Overridable so a run can pin the domain it was designed against without
# editing the working tree. Default unchanged.
DOMAIN = os.environ.get("KGLAMP_DOMAIN", "resources/robot3.pddl")
FD = "./downward/fast-downward.py"


def inject(pddl, atoms):
    """Insert atoms at the top of (:init ...), skipping any already present."""
    added = []
    m = re.search(r"\(:init\b", pddl)
    if not m:
        return pddl, added
    lower = pddl.lower()
    for a in atoms:
        if re.search(re.escape(a.lower()).replace(r"\ ", r"\s+"), lower):
            continue                       # already asserted, nothing to do
        added.append(a)
    if not added:
        return pddl, added
    at = m.end()
    return pddl[:at] + "\n" + "\n".join("    " + a for a in added) + pddl[at:], added


def plan_with(domain, problem, plan_path, log_path):
    work = tempfile.mkdtemp(prefix="fd_")
    out = subprocess.run(
        [sys.executable, FD, "--plan-file", plan_path,
         "--sas-file", os.path.join(work, "output.sas"),
         "--alias", "lama-first", domain, problem],
        capture_output=True, text=True).stdout
    open(log_path, "w").write(out)
    actions = []
    if os.path.exists(plan_path):
        actions = [l.strip().lower() for l in open(plan_path)
                   if l.strip().startswith("(")]
    return actions, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--problem", default=None,
                    help="default: problem.pddl in the run dir")
    ap.add_argument("--domain", default=DOMAIN)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--llm", action="store_true",
                    help="ask the model for the missing atoms instead of "
                         "deriving them; needs a running model server")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    d = args.run_dir
    # Prefer the syntax-repaired file: the raw one still carries undeclared
    # types and non-domain predicates that stop Fast Downward parsing, which
    # would read as "the injection did not help" when the file never parsed.
    prob = args.problem
    if not prob:
        for name in ("problem_repaired.pddl", "problem.pddl"):
            if os.path.exists(os.path.join(d, name)):
                prob = os.path.join(d, name); break

    edges = derive_dag(d)
    plan = load_plan(d)
    viols = check_plan(edges, plan, load_problem(d))

    print("run       : %s" % d)
    print("problem   : %s" % prob)
    print("plan      : %d action(s)" % len(plan))
    print("dag edges : %d" % len(edges))
    print("violations: %d" % len(viols))
    for v in viols:
        print(feedback(v, "init"))
    if not viols:
        print("\nnothing to repair.")
        return

    if args.llm:
        # The model's arm. Nothing is derived here: whatever survives screening
        # is the whole repair, so a model that does not return the fact returns
        # no repair and the violation stands.
        from scripts.dag_llm_init import llm_repair_atoms
        task = json.load(open(os.path.join(d, "report.json")))["task"]
        r = llm_repair_atoms(d, viols, open(prob).read(), task,
                             base_url=args.base_url, model=args.model, log_dir=d)
        print("\nasked  : %s @ %s" % (r.model, r.base_url))
        print("reply  : %s" % (r.raw.strip().replace("\n", " | ") or "(empty)"))
        for a, why in r.screened.redundant:
            print("  = %-30s %s" % (a, why))
        for a, why in r.screened.rejected:
            print("  x %-30s %s" % (a, why))
        print("the injector would have written: %s" % (r.dag_atoms or "(nothing)"))
        print("  agreed %s | missed %s | extra %s"
              % (r.agreed or "-", r.missed or "-", r.extra or "-"))
        atoms = sorted(r.screened.accepted)
    else:
        atoms = {v.edge.atom_init for v in viols}

        # A brake needs its release. (object-close Y) blocks PutObject until Y is
        # opened, but OpenObject requires (openable Y) - so injecting the closed
        # state into a problem whose affordance the model dropped seals the
        # container permanently and turns a wrong plan into no plan at all.
        # Both facts come from the same graph; inject them together.
        g = load_graph(d)
        for a in sorted(atoms):
            m = re.match(r"\(object-close\s+([^\s()]+)\)", a)
            if m and m.group(1) in g.openable:
                atoms.add("(openable %s)" % m.group(1))

        atoms = sorted(atoms)
    print("\natoms to inject: %s" % atoms)
    if args.dry_run:
        print("(dry run - nothing written)")
        return

    fixed, added = inject(open(prob).read(), atoms)
    if not added:
        print("every atom already present in :init - the violation is not a "
              "missing fact. Nothing injected.")
        return
    out_prob = os.path.join(d, "problem_injected.pddl")
    open(out_prob, "w").write(fixed)
    for a in added:
        print("  + %s   -> :init" % a)

    plan2, log = plan_with(args.domain, out_prob,
                           os.path.join(d, "plan_injected.plan"),
                           os.path.join(d, "plan_injected.log"))
    solved = "Solution found" in log
    print("\nreplan    : %s  (%d actions)" %
          ("Solution found" if solved else "NO PLAN", len(plan2)))
    for a in plan2:
        print("   " + a)

    viols2 = check_plan(edges, plan2, fixed)
    print("\nviolations before : %d" % len(viols))
    print("violations after  : %d" % len(viols2))
    for v in viols2:
        print(feedback(v, "init"))
    how = "from the model, screened" if args.llm else "no LLM involved"
    print("\nRESULT: %s" % ("DAG violation repaired (%s)." % how
                            if solved and not viols2 else
                            "violation persists."))


if __name__ == "__main__":
    main()

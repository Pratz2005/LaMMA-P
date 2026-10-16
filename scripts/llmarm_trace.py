"""Run the LLM repair arm on one saved run and write a readable trace.

    python scripts/llmarm_trace.py runs_llmarm/FP15_t0_easy

Takes a run directory that already contains a finished pipeline run (triplets,
stage outputs, problem file) and continues it through the Safety-DAG with the
model in the repair seat instead of the injector:

    DAG check -> prompt the model for the missing :init atoms -> screen ->
    inject what survives -> replan -> re-check

Writes `pipeline_trace_llmarm.txt`: the run's existing pipeline_trace.txt
verbatim, then the DAG check, the full repair prompt, the model's raw reply, the
screening verdict, the replan and the result. Nothing is transcribed by hand -
every line is read from the run or produced by Fast Downward on the spot.

Deliberately writes to a NEW file rather than overwriting pipeline_trace.txt, so
the deterministic run this continues from stays exactly as it was.

`trace_one` is the whole of the above as a function returning a record of what
happened; scripts/llmarm_sweep.py calls it across a run tree so the sweep numbers
and the traces can never disagree.
"""
import argparse
import json
import os
import sys

sys.path.append(".")
from scripts.safety_dag import derive_dag, check_plan, load_problem, load_plan
from scripts.make_evidence import (plan, inject, rule, llm_repair_section,
                                   dag_atoms, W, DOMAIN)
from scripts.dag_llm_init import llm_repair_atoms


def trace_one(d, container=None, out=None, timeout=300):
    """The LLM repair arm on one run dir. Writes the trace, returns a record.

    The record's `outcome` is the single field the results table keys on:

      NO_PDDL          the pipeline never produced a parseable problem file
      NO_PLAN_no_viol  no plan and no derived edge violated - nothing to see
      PLAN_OK_clean    planned, every derived edge satisfied (negative control)
      TIMEOUT          planner exceeded the budget before any check could run
      REPAIRED         violated, the model's atoms survived screening, and the
                       replan satisfies every edge
      still_violating  repaired plan still violates an edge
      no_repair        screening accepted nothing, so nothing was injected
      became_unsolvable  the injection turned a solvable file unsolvable
    """
    name = os.path.basename(os.path.abspath(d))
    rec = dict(run=name, outcome=None, rules=[], viol_before=0, viol_after=0,
               steps0=0, steps1=0, atoms=[], proposed=[], rejected=[],
               redundant=[], agreed=[], missed=[], extra=[], model_calls=0,
               task="", model=None, container=None)

    rep_path = os.path.join(d, "report.json")
    rep = json.load(open(rep_path)) if os.path.exists(rep_path) else {}
    rec["task"] = rep.get("task", "")

    pddl = load_problem(d)
    if not pddl.strip():
        rec["outcome"] = "NO_PDDL"
        return rec

    edges = derive_dag(d)
    # Plan the file the model produced. Use the same invocation everywhere so
    # the step counts in this trace cannot disagree with each other.
    acts, log0 = plan(pddl, timeout=timeout)
    viols = check_plan(edges, [a.lower() for a in acts], pddl)
    rec["steps0"] = len(acts)
    rec["viol_before"] = len(viols)
    rec["rules"] = sorted({v.edge.rule for v in viols})

    if not container and viols:
        container = (viols[0].edge.before[1] if len(viols[0].edge.before) > 1
                     else viols[0].edge.before[0])
    rec["container"] = container
    base = (container or "container").rsplit("_", 1)[0]

    L = []
    head = os.path.join(d, "pipeline_trace.txt")
    if os.path.exists(head):
        L.append(open(head).read().rstrip())
    L.append("\n\n" + rule("SAFETY-DAG CHECK   (reads the GRAPH, not the generated PDDL)"))
    fmt = lambda s: "%s(%s)" % (s[0], ", ".join(s[1:])) if s else "*"
    L.append("domain   : %s" % DOMAIN)
    L.append("planner  : %s, %d steps"
             % ("Solution found" if "Solution found" in log0 else "no plan", len(acts)))
    L.append("\nderived %d ordering edge(s) from the knowledge graph:" % len(edges))
    for e in edges:
        mark = "VIOLATED" if any(v.edge is e for v in viols) else "ok"
        L.append("   [%-8s] %s  <  %s      [%s]"
                 % (mark, fmt(e.before), fmt(e.after), e.rule))
    L.append("\nviolations: %d" % len(viols))
    for v in viols:
        L.append("   %s: required %s before %s"
                 % (v.reason, fmt(v.edge.before), fmt(v.edge.after)))

    out = out or os.path.join(d, "pipeline_trace_llmarm.txt")
    if not viols:
        rec["outcome"] = ("TIMEOUT" if log0 == "TIMEOUT" else
                          "PLAN_OK_clean" if "Solution found" in log0
                          else "NO_PLAN_no_viol")
        L.append("\nNothing to repair - the plan satisfies every derived edge.")
        L.append("\noutcome: %s" % rec["outcome"])
        open(out, "w").write("\n".join(L) + "\n")
        return rec

    L.append("\nThe planner reported success. The check runs regardless of planner")
    L.append("success, which is why it sees this at all.")

    # ---- the model's arm -----------------------------------------------------
    r = llm_repair_atoms(d, viols, pddl, rec["task"], log_dir=d)
    rec["model_calls"] = r.attempts
    rec["attempts"] = r.attempts
    rec["transcript"] = [dict(t) for t in r.transcript]
    rec["model"] = r.model
    rec["proposed"] = list(r.atoms)
    rec["rejected"] = ["%s  %s" % (a, why) for a, why in r.screened.rejected]
    rec["redundant"] = [a for a, _ in r.screened.redundant]
    rec["agreed"], rec["missed"], rec["extra"] = r.agreed, r.missed, r.extra
    # What the deterministic injector WOULD have written on this same violation.
    # Recorded but never merged into the accepted set - the arm stays single-pass
    # with no fallback. Keeping it means the deterministic comparison column can
    # be rebuilt later from CPU alone, without paying for the GPU job again.
    rec["dag_atoms"] = list(r.dag_atoms)

    fixed, added = inject(pddl, sorted(r.screened.accepted))
    acts2, log2 = plan(fixed, timeout=timeout)
    viols2 = check_plan(edges, [a.lower() for a in acts2], fixed)
    solved2 = "Solution found" in log2
    solved0 = "Solution found" in log0
    rec["atoms"], rec["steps1"], rec["viol_after"] = added, len(acts2), len(viols2)

    if not added:
        rec["outcome"] = "no_repair"
    elif solved2 and not viols2:
        rec["outcome"] = "REPAIRED"
    elif solved2:
        rec["outcome"] = "still_violating"
    elif solved0:
        rec["outcome"] = "became_unsolvable"
    else:
        rec["outcome"] = "still_no_plan"
    ok = rec["outcome"] == "REPAIRED"

    L.append("\n" + llm_repair_section(r, added, container or "?", base))

    L.append("\n" + rule("REPLAN" + ("" if added else "   (nothing was injected)")))
    L.append("planner: %s" % ("Solution found" if solved2 else "no plan"))
    for a in acts2:
        L.append("   %s%s" % (a, "   <-- INSERTED BY THE PLANNER"
                              if a.lower().startswith("(openobject") else ""))

    L.append("\n" + rule("VERDICT"))
    L.append("""   plan before repair : %d actions, %d of them OpenObject
   plan after  repair : %d actions, %d of them OpenObject
   DAG violations     : %d  ->  %d
   atoms injected     : %s
   model calls        : %d  (bounded retry on a fully rejected reply; the
                        screens gate every attempt and no deterministic
                        fallback stands behind them)

   repair source      : LANGUAGE MODEL  (%s)
   outcome            : %s
   %s"""
             % (len(acts), sum(1 for a in acts if a.lower().startswith("(openobject")),
                len(acts2), sum(1 for a in acts2 if a.lower().startswith("(openobject")),
                len(viols), len(viols2), ", ".join(added) or "none", r.attempts,
                r.model,
                rec["outcome"],
                "The task is now actually accomplished." if ok else
                "The violation survives; nothing was written that the graph did not assert."))

    open(out, "w").write("\n".join(L) + "\n")
    open(os.path.join(d, "problem_injected_llm.pddl"), "w").write(fixed)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--container", default=None,
                    help="receptacle the DAG rule fires on; inferred if omitted")
    ap.add_argument("--out", default=None)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    rec = trace_one(args.run_dir, container=args.container, out=args.out,
                    timeout=args.timeout)
    out = args.out or os.path.join(args.run_dir, "pipeline_trace_llmarm.txt")
    print("wrote %s" % out)
    print("outcome=%s  plan %d->%d  viol %d->%d  atoms=%s"
          % (rec["outcome"], rec["steps0"], rec["steps1"],
             rec["viol_before"], rec["viol_after"], rec["atoms"]))


if __name__ == "__main__":
    main()

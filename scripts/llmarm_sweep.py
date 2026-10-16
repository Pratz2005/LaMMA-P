"""The LLM repair arm across a whole run tree, with a machine-readable result.

    pixi run python scripts/llmarm_sweep.py --runs runs_4 \
        --tags scripts/nscc/tasks_all_final_test.tags --out runs_4/llmarm_sweep.json

One pass per run directory, all of it through scripts/llmarm_trace.trace_one, so
every number here is the same number that run's own
`pipeline_trace_llmarm.txt` shows:

    plan  ->  Safety-DAG check  ->  one model call for the missing :init atoms
          ->  three screening passes  ->  inject what survives  ->  replan  ->  re-check

Single pass per task: no resampling, and no deterministic fallback behind the
model. A task whose reply is rejected by screening is recorded as `no_repair`
and stays in the table as a failure, which is the point - a fallback would make
the arm unfalsifiable.

A task that raises is recorded as ERROR and the sweep continues; losing the
remaining tasks to one bad run dir would cost a GPU job.
"""
import argparse
import glob
import json
import os
import re
import sys
import traceback
from collections import Counter

sys.path.append(".")
from scripts.llmarm_trace import trace_one

RUN_RE = re.compile(r"^FP(\d+)_t(\d+)_(easy|complex|vague)_")


def load_tags(path):
    """(floor, index, tier) -> {tier, rules, task}, from the manifest sidecar."""
    d = {}
    if not path or not os.path.exists(path):
        return d
    for line in open(path):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("|", 5)
        if len(parts) < 6:
            continue
        floor, idx, dataset, tier, rules, task = parts
        d[(floor.strip(), idx.strip(), tier.strip())] = dict(
            dataset=dataset, tier=tier,
            eligible_rules=[] if rules.strip() == "-" else rules.split(","),
            task=task)
    return d


def key_of(name):
    m = RUN_RE.match(name)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs_4")
    ap.add_argument("--tags", default="scripts/nscc/tasks_all_final_test.tags")
    ap.add_argument("--out", default=None)
    ap.add_argument("--timeout", type=int, default=300,
                    help="Fast Downward budget per plan call, seconds")
    ap.add_argument("--resume", action="store_true",
                    help="keep records already in --out and skip those run dirs; "
                         "a job killed at walltime can be resubmitted without "
                         "paying for its finished model calls a second time")
    args = ap.parse_args()

    tags = load_tags(args.tags)
    out = args.out or os.path.join(args.runs, "llmarm_sweep.json")
    results = []
    done = set()
    if args.resume and os.path.exists(out):
        results = json.load(open(out))
        done = {r["run"] for r in results if r.get("outcome") != "ERROR"}
        print("resuming: %d run dirs already recorded in %s" % (len(done), out))

    dirs = sorted(glob.glob(os.path.join(args.runs, "FP*")))
    print("sweeping %d run dirs in %s" % (len(dirs), args.runs), flush=True)

    for d in dirs:
        name = os.path.basename(d)
        if name in done:
            continue
        if not os.path.isdir(d) or not os.path.exists(os.path.join(d, "triplets.json")):
            print("%-18s %s  (no triplets.json)" % ("SKIP", name), flush=True)
            continue
        try:
            rec = trace_one(d, timeout=args.timeout)
        except Exception as e:
            print("%-18s %s  %s" % ("ERROR", name, e), flush=True)
            traceback.print_exc()
            rec = dict(run=name, outcome="ERROR", error=str(e), rules=[],
                       viol_before=0, viol_after=0, steps0=0, steps1=0, atoms=[],
                       proposed=[], rejected=[], redundant=[], agreed=[],
                       missed=[], extra=[], model_calls=0, task="", model=None,
                       container=None)

        k = key_of(name)
        meta = tags.get(k, {}) if k else {}
        rec["floor"], rec["index"], rec["tier"] = (k if k else (None, None, None))
        rec["eligible_rules"] = meta.get("eligible_rules", [])
        rec["eligible"] = bool(rec["eligible_rules"])
        rec["dataset"] = meta.get("dataset")
        if meta.get("task") and not rec.get("task"):
            rec["task"] = meta["task"]
        results.append(rec)

        print("%-18s %-38s %-22s viol %d->%d  steps %d->%d  atoms=%s"
              % (rec["outcome"], name, ",".join(rec["rules"]) or "-",
                 rec["viol_before"], rec["viol_after"], rec["steps0"],
                 rec["steps1"], ",".join(rec["atoms"]) or "none"), flush=True)

        # written every iteration: a job killed at walltime still leaves the
        # tasks it did finish.
        json.dump(results, open(out, "w"), indent=1)

    json.dump(results, open(out, "w"), indent=1)

    print("\n===== summary =====")
    print(dict(Counter(r["outcome"] for r in results)))
    fired = [r for r in results if r["viol_before"]]
    print("\ntasks run              : %d" % len(results))
    print("eligible / ineligible  : %d / %d"
          % (sum(r["eligible"] for r in results),
             sum(not r["eligible"] for r in results)))
    print("check fired on         : %d" % len(fired))
    print("  of which ineligible  : %d   <- must be 0; these are the control"
          % sum(1 for r in fired if not r["eligible"]))
    print("repaired by the model  : %d"
          % sum(1 for r in results if r["outcome"] == "REPAIRED"))
    print("model proposed nothing usable (no_repair): %d"
          % sum(1 for r in results if r["outcome"] == "no_repair"))
    print("\nwrote %s" % out)


if __name__ == "__main__":
    main()

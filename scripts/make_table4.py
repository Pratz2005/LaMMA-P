"""Turn a llmarm_sweep.json into the paper's results table and a full report.

    python scripts/make_table4.py --sweep runs_4/llmarm_sweep.json --out-dir runs_4

Writes three files:

  TABLE.tex     the main table, in the column layout the paper already uses:
                task & plan actions before & DAG violations & atoms injected &
                plan actions after. One row per task the check fired on.
  TABLE_ext.tex the same rows with tier, rule family and outcome added, for a
                paper that has room for them.
  RESULTS.md    every task, the outcome breakdown, the per-tier and per-rule
                distribution, and the screening tally - the numbers to quote in
                prose rather than in the table.

Nothing here re-derives a result; it only formats what the sweep measured.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

# Outcomes where the Safety-DAG found something. Everything else is a task the
# check was silent on, and belongs in the prose, not the table.
FIRED = ("REPAIRED", "still_violating", "no_repair", "became_unsolvable",
         "still_no_plan")


def _generated(r, runs_dir="runs_4"):
    """Put-literals in this run's generated (:goal ...). Input metadata, not a
    re-derived result - it says what the goal stage emitted, nothing more."""
    for d in (os.path.join(runs_dir, r["run"]), r["run"]):
        for n in ("problem_repaired.pddl", "problem.pddl"):
            fp_ = os.path.join(d, n)
            if os.path.exists(fp_):
                t = open(fp_).read().lower()
                g = t[t.find("(:goal"):]
                return "%d put-literals" % len(
                    re.findall(r"\(at-location\s+[^\s()]+\s+[^\s()]+\)", g))
    return "?"


def _declared(r, data_dir="data/final_test"):
    """How many goal states the dataset declares for this task."""
    try:
        sys.path.append(".")
        from scripts.build_eligibility import load_rows
        rows = load_rows(os.path.join(data_dir, r["dataset"]))
        return "%d states" % len(rows[int(r["index"])].get("object_states") or [])
    except Exception:
        return "?"


def tex(s):
    """Escape the characters LaTeX would otherwise eat."""
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                 ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"),
                 ("}", r"\}"), ("~", r"\textasciitilde{}"),
                 ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    return s


def label(r, maxlen=58, dup=()):
    """`FloorPlan201 -- Task 0 (put the watch ...)` in the paper's own style.

    The same (floor, index) can appear in more than one prompt tier - MAT-THOR
    ships the plain, pddl and vague phrasings of a scene under their own
    numbering - so the tier is added only where it is needed to tell two rows
    apart. Unique rows keep the shorter form the paper already uses.
    """
    t = (r.get("task") or "").strip()
    t = t[:maxlen - 1].rstrip() + "…" if len(t) > maxlen else t
    tier = ""
    if (r.get("floor"), r.get("index")) in dup:
        tier = " [%s]" % (r.get("tier") or "?")
    return "FloorPlan%s -- Task %s%s (%s)" % (r.get("floor"), r.get("index"),
                                              tier, tex(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", default="runs_4/llmarm_sweep.json")
    ap.add_argument("--out-dir", default="runs_4")
    ap.add_argument("--maxlen", type=int, default=58)
    args = ap.parse_args()

    rs = json.load(open(args.sweep))
    os.makedirs(args.out_dir, exist_ok=True)
    fired = [r for r in rs if r["outcome"] in FIRED and r["viol_before"]]
    seen = Counter((r.get("floor"), r.get("index")) for r in fired)
    dup = {k for k, n in seen.items() if n > 1}
    order = {"REPAIRED": 0, "still_violating": 1, "no_repair": 2,
             "became_unsolvable": 3, "still_no_plan": 4}
    fired.sort(key=lambda r: (order.get(r["outcome"], 9), r["floor"] or "",
                              int(r["index"] or 0)))

    # ------------------------------------------------------------- TABLE.tex --
    L = [r"\begin{tabular}{lcccc}", r"\toprule",
         r"Task & Actions & Violations & Atoms & Actions \\",
         r" & (before) & detected & injected & (after) \\", r"\midrule"]
    for r in fired:
        L.append("%s & %d & %d & %d & %d \\\\"
                 % (label(r, args.maxlen, dup), r["steps0"], r["viol_before"],
                    len(r["atoms"]), r["steps1"]))
    L += [r"\bottomrule", r"\end{tabular}"]
    p = os.path.join(args.out_dir, "TABLE.tex")
    open(p, "w").write("\n".join(L) + "\n")
    print("wrote %s  (%d rows)" % (p, len(fired)))

    # --------------------------------------------------------- TABLE_ext.tex --
    E = [r"\begin{tabular}{lllccccccl}", r"\toprule",
         r"Task & Tier & Rule & Actions & Viol. & Atoms & Actions & Viol. & Calls & Outcome \\",
         r" & & & (before) & (before) & inj. & (after) & (after) & & \\", r"\midrule"]
    for r in fired:
        E.append("%s & %s & %s & %d & %d & %d & %d & %d & %d & %s \\\\"
                 % (label(r, args.maxlen, dup), r.get("tier") or "-",
                    tex(",".join(x.replace("_", " ") for x in r["rules"]) or "-"),
                    r["steps0"], r["viol_before"], len(r["atoms"]),
                    r["steps1"], r["viol_after"],
                    r.get("attempts", r.get("model_calls", 1)), tex(r["outcome"])))
    E += [r"\bottomrule", r"\end{tabular}"]
    p = os.path.join(args.out_dir, "TABLE_ext.tex")
    open(p, "w").write("\n".join(E) + "\n")
    print("wrote %s" % p)

    # ---------------------------------------------------------- RESULTS.md ----
    oc = Counter(r["outcome"] for r in rs)
    elig = [r for r in rs if r.get("eligible")]
    inel = [r for r in rs if not r.get("eligible")]
    fp = [r for r in inel if r["viol_before"]]
    by_tier = defaultdict(Counter)
    for r in rs:
        by_tier[r.get("tier") or "?"][r["outcome"]] += 1
    rule_n = Counter(x for r in rs for x in r["rules"])
    calls = sum(r.get("model_calls", 0) for r in rs)
    acc = sum(len(r["atoms"]) for r in rs)
    rej = sum(len(r["rejected"]) for r in rs)
    red = sum(len(r["redundant"]) for r in rs)
    prop = sum(len(r["proposed"]) for r in rs)

    M = ["# runs_4 - KGLAMP -> Safety-DAG -> LLM `:init` repair -> screening",
         "",
         "Generated by `scripts/make_table4.py` from `%s`." % args.sweep,
         "Every number is measured by `scripts/llmarm_sweep.py`; none is transcribed.",
         "The model gets up to KGLAMP_REPAIR_ATTEMPTS calls per violated task",
         "(default 3). Attempt 1 is greedy and seeded; a retry is issued only",
         "while the violation is still open, and it feeds back the screens' own",
         "verdicts, never the atom the model should have written. No",
         "deterministic fallback stands behind the model: every atom written to",
         "`:init` was produced by it and passed all three screens.",
         "",
         "## Scale", "",
         "| | |", "|---|---|",
         "| tasks run | %d |" % len(rs),
         "| eligible (a DAG rule *can* fire) | %d |" % len(elig),
         "| ineligible (negative control) | %d |" % len(inel),
         "| check fired | %d |" % len([r for r in rs if r["viol_before"]]),
         "| fired where the dataset's declared goal says it could not | %d |"
         % len(fp),
         "| model calls | %d |" % calls,
         "| repaired on the first (greedy) call | %d |"
         % sum(1 for r in rs if r["outcome"] == "REPAIRED"
               and r.get("attempts", 1) == 1),
         "| repaired only after a retry | %d |"
         % sum(1 for r in rs if r["outcome"] == "REPAIRED"
               and r.get("attempts", 1) > 1),
         ""]

    if fp:
        M += ["### The %d runs that fired outside the eligible set" % len(fp), "",
              "These are NOT the check firing on a correct plan. Eligibility is",
              "derived from the *dataset's* declared goal; the Safety-DAG derives",
              "its edges from the *generated* `(:goal ...)` block. When the goal",
              "stage collapses - emitting a put-literal for nearly every object",
              "in the scene instead of the one or two the task asks for - the",
              "generated goal demands things the declared goal never did, and the",
              "check reports ordering violations for those. The divergence is a",
              "goal-stage failure, not a check failure:", "",
              "| run | dataset declares | model generated |", "|---|---|---|"]
        for r in fp:
            M.append("| `%s` | %s | %s |"
                     % (r["run"], _declared(r), _generated(r)))
        M += ["",
              "This is also why the violation totals must not be quoted unsplit:",
              "a few collapsed goals dominate them.", ""]

    M += ["## Outcomes", "", "| outcome | n |", "|---|---|"]
    for k, v in oc.most_common():
        M.append("| `%s` | %d |" % (k, v))

    M += ["", "## By difficulty tier", "",
          "| tier | " + " | ".join(sorted(oc)) + " |",
          "|---" * (len(oc) + 1) + "|"]
    for t in ("easy", "complex", "vague"):
        if t in by_tier:
            M.append("| %s | %s |"
                     % (t, " | ".join(str(by_tier[t].get(k, 0)) for k in sorted(oc))))

    M += ["", "## Rule families that fired", "", "| rule | runs |", "|---|---|"]
    for k, v in rule_n.most_common():
        M.append("| `%s` | %d |" % (k, v))
    if not rule_n:
        M.append("| (none) | 0 |")

    M += ["", "## Screening", "",
          "The three passes between the model's reply and the problem file:",
          "syntax, vocabulary (predicate in the domain, arguments declared by",
          "the problem file), and truth (the knowledge graph must assert it).",
          "", "| | |", "|---|---|",
          "| atoms proposed by the model | %d |" % prop,
          "| accepted and injected | %d |" % acc,
          "| rejected | %d |" % rej,
          "| already in `:init` (not duplicated) | %d |" % red,
          "",
          "### Every rejection, with the pass that caught it", ""]
    any_rej = False
    for r in rs:
        for x in r["rejected"]:
            M.append("- `%s` — %s" % (r["run"], x))
            any_rej = True
    if not any_rej:
        M.append("(none)")

    M += ["", "## Every task", "",
          "| run | tier | eligible rules | outcome | calls | steps | viol | atoms | task |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rs, key=lambda r: r["run"]):
        M.append("| `%s` | %s | %s | `%s` | %d | %d→%d | %d→%d | %s | %s |"
                 % (r["run"], r.get("tier") or "-",
                    ",".join(r.get("eligible_rules") or []) or "-",
                    r["outcome"], r.get("attempts", r.get("model_calls", 0)),
                    r["steps0"], r["steps1"],
                    r["viol_before"], r["viol_after"],
                    ", ".join("`%s`" % a for a in r["atoms"]) or "-",
                    (r.get("task") or "").replace("|", "\\|")[:70]))

    p = os.path.join(args.out_dir, "RESULTS.md")
    open(p, "w").write("\n".join(M) + "\n")
    print("wrote %s" % p)
    print("\n--- TABLE.tex ---")
    print("\n".join(L))


if __name__ == "__main__":
    main()

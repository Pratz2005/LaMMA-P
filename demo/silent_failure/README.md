# A plan that runs, and silently fails the task

**Model:** Qwen2-7B-Instruct, vLLM, temperature 0, seed 0, repetition_penalty 1.05
**Scene:** AI2-THOR FloorPlan201
**Task:** "Put the vase on the dining table and open the book"
**Ground truth:** `DiningTable contains Vase`, `Book state OPENED`
**Run:** `logs/kgrun/FloorPlan201_t2_20260828-141851/`

## The plan Fast Downward produced

    (gotoobject  robot1 chair_2)
    (gotoobject  robot2 sidetable_1)
    (pickupobject robot2 vase_1 sidetable_1)
    (gotoobject  robot2 diningtable_1)
    (putobject   robot2 vase_1 diningtable_1)   <- correct
    (pickupobject robot1 book_1 chair_2)        <- picks the book up
    (gotoobject  robot1 desklamp_1)             <- hallucinated
    (switchon    robot1 desklamp_1)             <- hallucinated
    ; cost = 8

Solvable. Executable. **Wrong.**

* The book is never OPENED - it is only picked up. Ground truth requires
  `Book state OPENED`, so the task is not accomplished.
* Two of the eight actions serve a DeskLamp that appears nowhere in the task.

This is the dangerous case: the planner reports success, the plan executes to
completion, and the task is not done. Nothing in the symbolic pipeline signals a
problem.

## Three hallucinations, and why they hide each other

| stage | what it produced | error |
|---|---|---|
| 1 goal | `(object-open ?robot Book_1)`, `(switch-on ?robot DeskLamp_1)` | correctly parsed "open the book", then **invented a DeskLamp subgoal** |
| 3 property | kept `(has_capability Book_1 pickupable)` and `(isClosed Book_1)` | **dropped `(has_capability Book_1 openable)`** - it was given this on line 37 of its own prompt |
| 5 pddl | goal became `(holding robot1 book_1)` | **goal drift: "open" -> "hold"** |

The interaction is the interesting part. Stage 3 dropped the `openable`
affordance, which by itself would make opening the book impossible and the task
provably unsolvable - a loud, detectable failure. But stage 5 then drifted the
goal from *open* to *hold*, so the planner is never asked to open anything and
the missing affordance is never exercised.

Two errors that are each individually fatal combine to produce a plan that looks
completely healthy.

## The graph was correct

Verified against raw AI2-THOR metadata:

    Book.openable = True     Book.isOpen = False
    KG: ('Book_1','has_capability','openable')
    stage-3 prompt line 37: (has_capability Book_1 openable)

The model was given the fact and did not return it.

## What was and was not modified

* `scripts/property_prompt.py`, `relation_prompt.py`, `reach_prompt.py` -
  unmodified from the original commit.
* `scripts/goal_prompt.py` - its worked example used `(in ...)`, a predicate the
  domain does not define, contradicting `pddl_prompt.py`. Changed to
  `(at-location ...)`.
* `resources/robot3.pddl` - added `(openable ?object)` as a precondition of
  OpenObject / CloseObject. The domain previously modelled object STATE but not
  AFFORDANCE, so a dropped `openable` had no consequence and the error was
  invisible. Other affordances are declarable but do not gate actions.
* `scripts/pddl_prompt.py` - lists the new affordance predicates.
* The problem file was passed through `scripts/repair_pddl.py`, which fixes
  SYNTAX only (38 changes: duplicate declarations, an undeclared type,
  non-domain predicates) and reports every edit. It does not touch affordances,
  fact values or the goal.

No change was made to reduce hallucination.

## Reproduce

    qsub -v TASK=2 scripts/nscc/run_task.pbs

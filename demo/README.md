# Missing-affordance hallucination: a reproducible case

**Model:** Qwen2-7B-Instruct (vLLM, temperature 0, seed 0, repetition_penalty 1.05)
**Scene:** AI2-THOR FloorPlan201
**Task:** "Put the vase on the dining table and open the book"
(`data/final_test/FloorPlan201.json`, index 2; robots `[25, 23]`)
**Run artifacts:** `logs/kgrun/FloorPlan201_t2_20260828-121918/`

## Claim

The knowledge graph is derived mechanically from AI2-THOR metadata and is
correct. The LLM was given the fact it needed, dropped it, and that single
omission makes the task provably impossible for the planner.

## Evidence chain

| stage | content | status |
|---|---|---|
| AI2-THOR metadata | `Book.openable = True`, `Book.isOpen = False` | ground truth |
| Knowledge graph | `('Book_1','has_capability','openable')` | faithful |
| Stage-3 prompt, line 37 | `(has_capability Book_1 openable)` | **model was told** |
| Stage-3 output | `(has_capability Book_1 pickupable)` kept<br>`(isClosed Book_1)` kept<br>`openable` **absent** | **omission** |
| problem.pddl | no `(openable Book_1)` | propagated |
| Fast Downward | `OpenObject` requires `(openable ?object)` -> inapplicable | unsolvable |

The model kept the *state* (`isClosed`) and dropped the *affordance*
(`openable`) - from adjacent lines of the same list. Line 36 kept, line 37
dropped, line 38 kept.

This is the failure described in the LaMMA-P paper: "encoding a box as
(box, has state, closed) without specifying that it is openable prevents the
planner from retrieving its contents."

## Result A - zero intervention (the strongest version)

The model's own goal, its own facts, nothing substituted. Only the 39 mechanical
syntax repairs, which touch no semantics.

    demo/1_repaired_asis.pddl        model output, syntax repaired   -> UNSOLVABLE
    demo/4_ownGoal_plusAfford.pddl   + the 2 dropped affordances     -> 9-step plan

    $ diff demo/1_repaired_asis.pddl demo/4_ownGoal_plusAfford.pddl
    14a15,16
    >     (pickupable Vase_1)
    >     (pickupable Book_1)

The plan that becomes possible:

    (gotoobject robot1 chair_2)
    (pickupobject robot1 book_1 chair_2)
    (gotoobject robot1 desklamp_1)
    (switchon robot1 desklamp_1)
    (gotoobject robot1 diningtable_1)
    (gotoobject robot1 sidetable_1)
    (pickupobject robot1 vase_1 sidetable_1)
    (gotoobject robot1 diningtable_1)
    (putobject robot1 vase_1 diningtable_1)

The model's plan is impossible solely because it dropped affordances it was
given. No goal was changed to produce this.

## Result B - the `openable` story specifically

Stage 5 drifted the goal from "open the book" to `(holding robot1 Book_1)`, so
the model's literal final goal never requires OpenObject; the blocker there is
the dropped `pickupable`. To demonstrate the `openable` omission specifically,
the goal is taken from the pipeline's own STAGE 1 output,
`(object-open ?robot Book_1)`, with the free variable bound to `robot2` (the
only robot in this task with the OpenObject skill).

This is an intervention and is declared as such - it is passed as a visible
`--goal` flag, not hidden. The goal drift is itself a second finding.

## The demonstration

The model's raw output also contained syntax errors (31 uses of an undeclared
type, 4 duplicate declarations, 2 non-domain predicates). Those stop Fast
Downward parsing the file at all, so the semantic error underneath is never
reached. `scripts/repair_pddl.py` removes ONLY the syntax noise and reports
every edit; it does not touch affordances, fact values, or the goal.

The goal is taken from the pipeline's own stage-1 output,
`(object-open ?robot Book_1)`, with the free variable bound to `robot2` -
the only robot in this task with the `OpenObject` skill.

Two files, differing by exactly one line:

    $ diff 2_missing_openable.pddl 3_with_openable.pddl
    14a15
    >     (openable Book_1)

Result:

| file | `(openable Book_1)` | planner |
|---|---|---|
| `2_missing_openable.pddl` | absent, as the model left it | **unsolvable**, search exit 12 |
| `3_with_openable.pddl` | present | **Solution found**, 2 steps |

The plan that becomes possible once the dropped fact is restored:

    (gotoobject robot2 book_1)
    (openobject robot2 book_1)

## Reproduce

    export LD_LIBRARY_PATH=/app/apps/gcc/12.3.0-nscc/lib64:$LD_LIBRARY_PATH
    ./downward/fast-downward.py --alias lama-first \
        resources/robot3.pddl demo/2_missing_openable.pddl    # unsolvable
    ./downward/fast-downward.py --alias lama-first \
        resources/robot3.pddl demo/3_with_openable.pddl       # solves

## Limitations to state honestly

* The graph is faithful to AI2-THOR metadata, but that metadata contains
  axis-aligned-bounding-box artifacts: a chair tucked under a table is reported
  as containing the table. Not implicated in this finding - `openable` is a
  boolean flag on the object, not a geometric inference.
* The same run also shows goal drift (stage 5 turned "open the book" into
  `(holding robot1 Book_1)`) and an invented subgoal
  (`(switch-on robot1 DeskLamp_1)`, absent from the task). Separate errors.
* One case, one seed. A rate needs the other tasks.

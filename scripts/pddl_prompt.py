def build_pddl_prompt(goal: str, relation: str, property_: str, reach: str) -> str:
    prompt = f"""## 1. Contextual Example
A Problem PDDL instantiates the domain for a specific scenario: it declares the objects
that exist, the initial state as a conjunction of ground predicates, and the goal condition.

Example:
(define (problem example_problem)
  (:domain robot3)
  (:objects
    robot1 - robot
    Watch_1 KeyChain_1 Drawer_1 location_1 - object
  )
  (:init
    (at robot1 location_1)
    (at-location Watch_1 location_1)
    (at-location KeyChain_1 location_1)
    (at-location Drawer_1 location_1)
  )
  (:goal
    (and
      (at-location Watch_1 Drawer_1)
      (at-location KeyChain_1 Drawer_1)
    )
  )
)

## 2. Task Constraints
Goal: {goal}

## 3. Define the World and Agent
Relation:
{relation}

Property:
{property_}

Reach:
{reach}

## 4. Define Problem Structure & Robot Logic
The domain is `robot3`, with types `robot` and `object`, and predicates:
(at ?robot ?object), (at-location ?object ?location), (holding ?robot ?object),
(inaction ?robot), (switch-on ?robot ?object), (switch-off ?robot ?object),
(object-open ?robot ?object), (object-close ?robot ?object), (break ?robot ?object),
(sliced ?object), (cleaned ?robot ?object).
1. Objects: Declare every robot and every object referenced in the Relation, Property, or Reach sections above (including location symbols) under `:objects`.
2. Initial state: Encode the Relation, Property, and Reach tuples as `:init` predicates using only the domain predicates listed above.
3. Goal: Encode the Goal as the `:goal` condition, using only entities declared in `:objects`.
4. Grounding: Do not invent objects, robots, or predicates that are not present in the sections above or the domain predicate list.
5. Never use "not" inside `:init`. PDDL's closed-world assumption means any predicate not listed there is already false — only list positive ground facts in `:init`. "not" may only appear inside `:goal` or action preconditions, never in `:init`.
6. Never declare `(inaction ?robot)` in `:init`. Every action in the domain requires `(not (inaction ?robot))` as a precondition and no action ever removes `inaction` — if a robot starts as `inaction`, no action involving it will ever be applicable and the problem becomes unsolvable. Simply omit the `inaction` predicate for every robot.
7. Open/closed containers: the Property section's `(isOpen X)` and `(isClosed X)` facts are not domain predicates themselves — translate them. `(isOpen X)` becomes `(object-open ?robot X)`; `(isClosed X)` becomes `(object-close ?robot X)`. PickupObject and PutObject both require `(not (object-close ?robot ?location))` for whichever robot performs the action, so a closed container's `(object-close ?robot X)` fact must be declared once for *every* robot in `:objects`, not just one — otherwise a different robot could bypass the closed check. A container with no isOpen/isClosed fact needs no object-open/object-close facts at all (open by default).
8. Output ONLY the PDDL code in a single ```pddl code block, starting with `(define (problem ...)` and ending with the matching closing parenthesis. Do not include any prose, explanation, or headings before or after the code block.

## 5. Generate PDDL problem
"""
    return prompt

def build_pddl_prompt(goal: str, relation: str, property_: str, reach: str) -> str:
    prompt = f"""## 1. Contextual Example
A Problem PDDL instantiates the domain for a specific scenario: it declares the objects
that exist, the initial state as a conjunction of ground predicates, and the goal condition.

Example:
(define (problem example_problem)
  (:domain robot3)
  (:objects
    robotX - robot
    ObjectA_1 ObjectB_1 ReceptacleA_1 location_901 - object
  )
  (:init
    (at robotX location_901)
    (at-location ObjectA_1 location_901)
    (at-location ObjectB_1 location_901)
    (at-location ReceptacleA_1 location_901)
    (openable ReceptacleA_1)
    (pickupable ObjectA_1)
    (pickupable ObjectB_1)
  )
  (:goal
    (and
      (at-location ObjectA_1 ReceptacleA_1)
      (at-location ObjectB_1 ReceptacleA_1)
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
(inaction ?robot), (switch-on ?object), (switch-off ?object),
(object-open ?object), (object-close ?object), (break ?object),
(sliced ?object), (cleaned ?object),
(openable ?object), (pickupable ?object), (sliceable ?object), (toggleable ?object).
1. Objects: Declare every robot and every object referenced in the Relation, Property, or Reach sections above (including location symbols) under `:objects`.
2. Initial state: Encode the Relation, Property, and Reach tuples as `:init` predicates using only the domain predicates listed above.
3. Goal: Encode the Goal as the `:goal` condition, using only entities declared in `:objects`.
4. Grounding: Do not invent objects, robots, or predicates that are not present in the sections above or the domain predicate list. The example in section 1 uses placeholder names (robotX, ObjectA_1, location_901) that do not exist in this scene - never copy them into your answer.
5. Never use "not" inside `:init`. PDDL's closed-world assumption means any predicate not listed there is already false — only list positive ground facts in `:init`. "not" may only appear inside `:goal` or action preconditions, never in `:init`.
6. Never declare `(inaction ?robot)` in `:init`. Every action in the domain requires `(not (inaction ?robot))` as a precondition and no action ever removes `inaction` — if a robot starts as `inaction`, no action involving it will ever be applicable and the problem becomes unsolvable. Simply omit the `inaction` predicate for every robot.
7. Object state: the Property section's `(isOpen X)`, `(isClosed X)` and `(isToggled X)` facts are not domain predicates themselves — translate them. `(isOpen X)` becomes `(object-open X)`; `(isClosed X)` becomes `(object-close X)`; `(isToggled X)` becomes `(switch-on X)`. These describe the object, not a robot, so each is declared exactly ONCE with a single argument — never once per robot, and never with a robot argument. PickupObject and PutObject require `(not (object-close ?location))`, so a container asserted closed blocks every robot equally. A container with no isOpen/isClosed fact needs no object-open/object-close fact at all (open by default).
8. Affordances are SEPARATE from state and both must be stated. `(has_capability X openable)` in the Property section becomes `(openable X)` in `:init`; likewise `pickupable` -> `(pickupable X)`, `sliceable` -> `(sliceable X)`, `toggleable` -> `(toggleable X)`. The `openable` affordance is what makes opening legal at all: OpenObject and CloseObject both require `(openable ?object)`. Stating that a container is closed while omitting `(openable X)` makes it permanently unopenable and its contents unreachable. Never drop an affordance the Property section lists, and never assert one it does not.
9. Output ONLY the PDDL code in a single ```pddl code block, starting with `(define (problem ...)` and ending with the matching closing parenthesis. Do not include any prose, explanation, or headings before or after the code block.

## 5. Generate PDDL problem
"""
    return prompt

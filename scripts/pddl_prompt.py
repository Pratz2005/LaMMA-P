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
    (inaction robot1)
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
2. Initial state: Encode the Relation, Property, and Reach tuples as `:init` predicates using only the domain predicates listed above. Every robot must start with `(inaction ?robot)`.
3. Goal: Encode the Goal as the `:goal` condition, using only entities declared in `:objects`.
4. Grounding: Do not invent objects, robots, or predicates that are not present in the sections above or the domain predicate list.

## 5. Generate PDDL problem
"""
    return prompt

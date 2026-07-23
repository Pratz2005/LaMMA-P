def format_property_triplet(triplet):
    subject, relation, value = triplet
    if isinstance(value, bool):
        if value:
            return f"({relation} {subject})"
        return f"(not ({relation} {subject}))"
    return f"({relation} {subject} {value})"


def build_property_prompt(goal: str, task: str, relation: str, property_triplets: list) -> str:
    property_tuples_text = "\n".join(format_property_triplet(t) for t in property_triplets)

    prompt = f"""## 1. Contextual Example
Properties describe object attributes and robot capabilities that constrain feasible actions.
- Capability: (has_capability ?entity ?skill) — the entity (object or robot) supports that skill/action.
- State: (?state ?obj) — the object currently has that boolean state true; (not (?state ?obj)) means false.

Example:
(has_capability Apple_1 pickupable)
(isOpen Fridge_1)
(not (isOpen Drawer_1))
(has_capability RobotA pickup)

## 2. Scenario
Goal: {goal}
Task: {task}
Relation: {relation}

## 3. Object Properties
Property Tuples:
{property_tuples_text}

## 4. Output Constraints
Generate the property condition as a PDDL (:init) format.
1. Relations: Only include predicates of type "has_capability" (capabilities) or object/robot state predicates.
2. Relevance: Only include entities that are related to the Goal, Task, or Relation. Ignore irrelevant background clutter.
"""
    return prompt

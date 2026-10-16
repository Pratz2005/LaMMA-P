def format_property_triplet(triplet):
    subject, relation, value = triplet
    if isinstance(value, bool):
        if value:
            return f"({relation} {subject})"
        if relation == "isOpen":
            # False needs its own positive fact - the domain models "closed" as a
            # distinct predicate (object-close), not the mere absence of isOpen.
            return f"(isClosed {subject})"
        return None
    return f"({relation} {subject} {value})"


def build_property_prompt(goal: str, task: str, relation: str, property_triplets: list) -> str:
    lines = [format_property_triplet(t) for t in property_triplets]
    property_tuples_text = "\n".join(line for line in lines if line is not None)

    prompt = f"""## 1. Contextual Example
Properties describe object attributes and robot capabilities that constrain feasible actions.
- Capability: (has_capability ?entity ?skill) — the entity (object or robot) supports that skill/action.
- State: (?state ?obj) — the object currently has that boolean state true. If a state is false, omit it
  entirely; PDDL's closed-world assumption means any predicate not listed in :init is already false.
  Exception: openable containers that start closed (isOpen: false) must be stated explicitly as
  (isClosed ?obj) — a closed container blocks pickup/put actions targeting it, so this fact is safety-critical
  and must never be silently dropped like other false states.

Example:
(has_capability ObjectA_1 pickupable)
(isOpen ReceptacleA_1)
(isClosed ReceptacleB_1)
(has_capability robotX pickup)

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
3. Never use "not" in this output. Only list positive facts — a state that is false should simply be omitted.
"""
    return prompt

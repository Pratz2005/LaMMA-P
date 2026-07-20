def format_triplet_as_pddl(triplet):
    subject, relation, obj = triplet
    return f"({relation} {subject} {obj})"


def build_relation_prompt(goal: str, task: str, scene_triplets: list) -> str:
    scene_tuples_text = "\n".join(format_triplet_as_pddl(t) for t in scene_triplets)

    prompt = f"""## 1. Contextual Example
Relations describe the physical hierarchy of the scene (containers and surfaces).
- Containment: (inside ?obj ?container) — the object is enclosed inside the container.
- Support: (on ?obj ?surface) — the object rests on top of the surface.

Example:
(inside Apple_1 Fridge_1)
(on Plate_1 CounterTop_1)

## 2. Scenario
Goal: {goal}
Task: {task}

## 3. Spatial Data
Scene Tuples:
{scene_tuples_text}

## 4. Output Constraints
Generate the relationship condition as a PDDL (:init) format.
1. Relations: Only include relations of type "inside" (containment) or "on" (support).
2. Relevance: Only include objects that are related to the Goal or Task. Ignore irrelevant background clutter.
"""
    return prompt

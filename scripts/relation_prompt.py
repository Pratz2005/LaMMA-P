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
(inside ObjectA_1 ReceptacleA_1)
(on ObjectB_1 SurfaceA_1)

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
3. Source: Every tuple you output must appear verbatim in the Scene Tuples above. Copy it
   unchanged - do not reword, re-case, merge or invent tuples. The example above uses
   placeholder names that do not exist in this scene; never copy them into your answer.
4. Time: the Scene Tuples describe the world BEFORE any robot has acted. The Goal is shown
   only so you can judge which objects matter. Never emit a relation because the Goal
   requires it - if the Goal says an object should end up in a container, and the Scene
   Tuples place it somewhere else, report where the Scene Tuples place it.
"""
    return prompt

def build_goal_prompt(task: str, objects: list) -> str:
    object_ids_text = "\n".join(obj["objectId"] for obj in objects)

    prompt = f"""## 1. Contextual Example
A Goal is a formal, structured target state derived from a natural-language Task,
grounded against the objects that actually exist in the environment.

Example:
Task: "put ObjectA and ObjectB inside ReceptacleA, and switch off DeviceA"
Objects: ObjectA_1, ObjectB_1, ReceptacleA_1, DeviceA_1, ...
Goal:
(at-location ObjectA_1 ReceptacleA_1)
(at-location ObjectB_1 ReceptacleA_1)
(switch-off DeviceA_1)

## 2. Task
{task}

## 3. Objects
{object_ids_text}


## 4. Output Constraints
Generate the Goal as a set of PDDL-style predicate tuples.
1. Grounding: Only use object identifiers that appear in the Objects list above. Do not
   invent objects. The example above uses placeholder names that do not exist in this
   scene - never copy them into your answer.
2. Relevance: Only include goal conditions implied by the Task. Ignore objects unrelated to the Task.
3. Format: One predicate tuple per line, e.g. "(predicate arg1 arg2)".
   A goal describes the state of the WORLD, not which robot brings it about, so no
   goal predicate takes a robot argument. Write (switch-off LightSwitch_1), never
   (switch-off robot1 LightSwitch_1) - the extra argument makes the file unparseable.
4. Predicates: use ONLY predicates the domain defines --
   (at-location ?object ?location) for "X is in/on/at Y",
   (object-open ?object) for "X is open",
   (object-close ?object) for "X is closed",
   (sliced ?object), (break ?object), (cleaned ?object),
   (switch-on ?object) for "X is on", (switch-off ?object) for "X is off".
   Do NOT invent predicates such as "in", "on", "open" or "inside" - the planner
   rejects the whole problem file if the goal names a predicate the domain lacks.
"""
    return prompt

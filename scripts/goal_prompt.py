def build_goal_prompt(task: str, objects: list) -> str:
    object_ids_text = "\n".join(obj["objectId"] for obj in objects)

    prompt = f"""## 1. Contextual Example
A Goal is a formal, structured target state derived from a natural-language Task,
grounded against the objects that actually exist in the environment.

Example:
Task: "put the watch and keychain inside the drawer"
Objects: Watch_1, KeyChain_1, Drawer_1, ...
Goal:
(in Watch_1 Drawer_1)
(in KeyChain_1 Drawer_1)

## 2. Task
{task}

## 3. Objects
{object_ids_text}

## 4. Output Constraints
Generate the Goal as a set of PDDL-style predicate tuples.
1. Grounding: Only use object identifiers that appear in the Objects list above. Do not invent objects.
2. Relevance: Only include goal conditions implied by the Task. Ignore objects unrelated to the Task.
3. Format: One predicate tuple per line, e.g. "(predicate arg1 arg2)".
"""
    return prompt

def format_reach_triplet(triplet):
    subject, relation, location = triplet
    return f"({relation} {subject} {location})"


def build_reach_prompt(relation: str, property_: str, reach_triplets: list) -> str:
    reach_tuples_text = "\n".join(format_reach_triplet(t) for t in reach_triplets)

    prompt = f"""## 1. Contextual Example
Reachability links entities (objects and robots) to discrete navigable locations,
grounding goals and actions to reachable target positions.
- Location: (has_location ?entity ?location) — the entity is nearest to that discrete location.

Example:
(has_location ObjectA_1 location_901)
(has_location robotX location_902)

## 2. Task Constraints
Relation: {relation}
Property: {property_}

## 3. Output Format
Location Tuples:
{reach_tuples_text}

Generate the reachability condition as a PDDL (:init) format.
1. Relations: Only include predicates of type "has_location".
2. Relevance: Only include entities that are related to the Relation or Property. Ignore irrelevant background clutter.

## 4. Generate Reachability Tuple
"""
    return prompt

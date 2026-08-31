"""Shared PDDL parsing helpers and the domain vocabulary.

Lives in its own module because both the checker (run_kg_task) and the syntax
repairer (repair_pddl) need it, and having either import the other creates a
cycle.
"""

import re

# Predicates declared in resources/robot3.pddl. Anything outside this set that
# appears in generated PDDL is fabricated - the model cannot have got it from
# the domain, and the KG never produces it.
DOMAIN_PREDICATES = {
    "at", "at-location", "holding", "inaction", "switch-on", "switch-off",
    "object-open", "object-close", "break", "sliced", "cleaned",
    # affordances - separate from state, and preconditions of the actions that
    # use them (see the affordance note in resources/robot3.pddl)
    "openable", "pickupable", "sliceable", "toggleable",
}
# affordance predicate -> the AI2-THOR capability flag the KG records
AFFORDANCES = {"openable": "openable", "pickupable": "pickupable",
               "sliceable": "sliceable", "toggleable": "toggleable"}
DOMAIN_TYPES = {"robot", "object"}


def _section(pddl: str, name: str) -> str:
    """Return the body of a top-level (:name ...) section, brace-balanced."""
    marker = f"(:{name}"
    idx = pddl.lower().find(marker)
    if idx == -1:
        return ""
    depth = 0
    for i in range(idx, len(pddl)):
        if pddl[i] == "(":
            depth += 1
        elif pddl[i] == ")":
            depth -= 1
            if depth == 0:
                return pddl[idx + len(marker):i]
    return pddl[idx + len(marker):]


def parse_facts(section_text: str) -> list:
    """Every (pred arg arg ...) form in a section, as [pred, arg, ...] lists."""
    facts = []
    for match in re.finditer(r"\(([^()]*)\)", section_text):
        tokens = match.group(1).split()
        if tokens:
            facts.append([t.lower() for t in tokens])
    return facts


def parse_objects(section_text: str) -> dict:
    """Parse a `:objects` block into {symbol: declared_type}.

    Walks tokens rather than pattern-matching: PDDL names may legally contain
    '-', so a regex for "names then a dash then a type" cannot tell a separator
    from part of an identifier. The grammar is simply `name+ - type` repeated,
    with any trailing names untyped.
    """
    declared = {}
    tokens = section_text.replace("\n", " ").replace("(", " ").replace(")", " ").split()
    pending = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "-":
            typ = tokens[i + 1].lower() if i + 1 < len(tokens) else None
            for name in pending:
                declared[name.lower()] = typ
            pending = []
            i += 2
            continue
        pending.append(tokens[i])
        i += 1
    for name in pending:          # names declared without a type
        declared.setdefault(name.lower(), None)
    return declared

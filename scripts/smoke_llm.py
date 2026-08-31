"""Smoke test for a locally served, OpenAI-compatible LLM endpoint.

Deliberately standalone - imports nothing from scripts/, so a broken pipeline
module cannot make this report a false failure. Two probes:

  1. liveness  - trivial chat completion, proves the server answers at all
  2. PDDL      - asks for a problem file the way pddl_prompt.py asks, and checks
                 the reply actually parses

The second probe is the one that matters. "The model replies to hello" says
almost nothing about whether a 7B model can drive this pipeline; "the model
emits a balanced (define (problem ...)) when prompted our way" says a lot.

Exits non-zero if either probe fails, so the PBS job fails loudly instead of
leaving a bad result buried in a log.
"""

import os
import sys
import time

from openai import OpenAI

BASE_URL = os.environ.get("KGLAMP_LLM_BASE_URL", "http://localhost:8000/v1")
MODEL = os.environ.get("KGLAMP_MODEL", "Qwen/Qwen2-7B-Instruct")

# Mirrors the shape of scripts/pddl_prompt.py: a domain predicate list, grounded
# objects, and the "output only a pddl code block" instruction. Kept small so a
# failure here means the model cannot do the task, not that it ran out of tokens.
PDDL_PROBE = """## 1. Contextual Example
A Problem PDDL instantiates a domain: it declares the objects that exist, the
initial state as ground predicates, and the goal condition.

## 2. Domain
The domain is `robot3`, with types `robot` and `object`, and predicates:
(at ?robot ?object), (at-location ?object ?location), (holding ?robot ?object),
(object-open ?robot ?object), (object-close ?robot ?object), (sliced ?object).

## 3. Scene
robot1 - robot
Apple_1 Fridge_1 CounterTop_1 location_1 location_2 - object
(at-location Apple_1 CounterTop_1)
(at-location Fridge_1 location_2)
(at robot1 location_1)
(object-close robot1 Fridge_1)

## 4. Task
Put the apple in the fridge.

## 5. Output Constraints
1. Declare every robot and object under `:objects`.
2. Encode the scene facts as `:init`.
3. Never use "not" inside `:init`.
4. Output ONLY the PDDL in a single ```pddl code block, starting with
   `(define (problem ...)` and ending with the matching closing parenthesis.
"""


def extract_pddl_block(text: str) -> str:
    """Pull the bare (define (problem ...) ...) s-expression out of LLM output.

    Same contract as extract_pddl_block in scripts/kglamp_pipeline.py - if this
    fails here, it will fail there too, which is exactly what we want to learn.
    """
    import re

    fence = re.search(r"```(?:pddl)?\s*(.*?)```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text

    start = candidate.find("(define")
    if start == -1:
        raise ValueError("no '(define ...)' block in output")

    depth = 0
    for i in range(start, len(candidate)):
        if candidate[i] == "(":
            depth += 1
        elif candidate[i] == ")":
            depth -= 1
            if depth == 0:
                return candidate[start:i + 1].strip()
    raise ValueError("unbalanced parentheses in output")


def main() -> int:
    print(f"endpoint : {BASE_URL}")
    print(f"model    : {MODEL}")
    client = OpenAI(base_url=BASE_URL, api_key="EMPTY")

    print("\n=== served models ===")
    try:
        for m in client.models.list().data:
            print(" ", m.id)
    except Exception as exc:
        print(f"!! could not list models: {exc}")
        return 1

    # ---- probe 1: liveness -------------------------------------------------
    print("\n=== probe 1: liveness ===")
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Reply with exactly: PIPELINE OK"}],
            max_tokens=16,
            temperature=0,
        )
    except Exception as exc:
        print(f"!! FAILED: {exc}")
        return 1
    dt = time.time() - t0
    reply = r.choices[0].message.content.strip()
    out_tok = r.usage.completion_tokens if r.usage else 0
    print(f"reply    : {reply!r}")
    print(f"latency  : {dt:.2f}s for {out_tok} tokens ({out_tok / dt:.1f} tok/s)")

    # ---- probe 2: can it actually produce PDDL? ----------------------------
    print("\n=== probe 2: PDDL generation ===")
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": PDDL_PROBE}],
            max_tokens=1024,
            temperature=0,
        )
    except Exception as exc:
        print(f"!! FAILED: {exc}")
        return 1
    dt = time.time() - t0
    raw = r.choices[0].message.content
    out_tok = r.usage.completion_tokens if r.usage else 0
    print(f"latency  : {dt:.2f}s for {out_tok} tokens ({out_tok / dt:.1f} tok/s)")
    print("\n--- raw output ---")
    print(raw)

    print("\n--- parsed ---")
    try:
        block = extract_pddl_block(raw)
    except ValueError as exc:
        print(f"!! PARSE FAILED: {exc}")
        print("!! The model answered but not in a form the pipeline can consume.")
        return 1
    print(block)

    # Cheap sanity checks mirroring the pipeline's hard requirements.
    problems = []
    low = block.lower()
    if ":objects" not in low:
        problems.append("no :objects section")
    if ":init" not in low:
        problems.append("no :init section")
    if ":goal" not in low:
        problems.append("no :goal section")

    print("\n=== result ===")
    if problems:
        print("!! block parsed but is malformed: " + "; ".join(problems))
        return 1

    print("both probes passed - model is usable by the pipeline")
    return 0


if __name__ == "__main__":
    sys.exit(main())

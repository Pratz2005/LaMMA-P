"""Derive which dataset tasks CAN exhibit a DAG-fixable precondition failure.

    python scripts/build_eligibility.py --data data/MAT2THOR \
        --manifest scripts/nscc/tasks_eligible_mat2.manifest

Selection uses only two inputs, both fixed before any model runs:

  * the task row's declared goal (`object_states`), and
  * the scene's AI2-THOR metadata fixture (openable / isOpen / isToggled /
    parentReceptacles).

No model output is consulted, so the eligible set cannot be shaped by what the
pipeline happened to produce. That is the property that makes the run set a
pre-registration rather than a post-hoc selection, and it is why this exists as
a script instead of a hand-written list: a reviewer can re-run it.

Four rules, matching scripts/safety_dag.py:

  R1 open_before_put      goal puts X into Y; Y is openable and currently closed
  R2 open_before_pickup   a goal object starts inside a closed openable container
  R3 open_goal            goal demands an object be OPENED
  R4 toggle_needed        goal demands ON/OFF and the scene is in the opposite state

A task is eligible if it carries at least one tag. Writes the manifest plus a
sidecar .tags file recording which rules fired, so the distribution can be
reported without re-deriving it.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

sys.path.append(".")

FIXTURES = "resources/kg_fixtures"


def load_rows(path):
    """Task rows from a jsonl file, tolerating the dataset's quirks.

    MAT-THOR writes Python's None rather than JSON null on some lines (they were
    produced with str(dict)), and four lines are missing a closing bracket on
    object_states. Both are repaired here rather than skipped: a task dropped for
    a syntax defect would silently shrink the eligible set.
    """
    rows = []
    for i, line in enumerate(open(path)):
        if not line.strip():
            continue
        s = re.sub(r":\s*None\b", ": null", line)
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError:
            fixed = re.sub(r"(\"object_states\"\s*:\s*\[.*?\})\s*,\s*(\"trans\")",
                           r"\1], \2", s, flags=re.S)
            try:
                rows.append(json.loads(fixed))
            except json.JSONDecodeError:
                print("  !! unparseable %s:%d - skipped" % (path, i + 1))
                rows.append({"task": "", "object_states": [], "_bad": True})
    return rows


def scene(floor):
    p = os.path.join(FIXTURES, "FloorPlan%s_metadata.json" % floor)
    if not os.path.exists(p):
        return None
    return json.load(open(p))["objects"]


def by_type(objs):
    """objectType (lowercased) -> list of that type's metadata dicts."""
    d = {}
    for o in objs:
        d.setdefault(str(o.get("objectType", "")).lower(), []).append(o)
    return d


def closed_openable(objs, name):
    """Is any instance of this object type openable AND currently closed?"""
    return any(o.get("openable") and o.get("isOpen") is False
               for o in by_type(objs).get(str(name).lower(), []))


def toggled(objs, name):
    """Current isToggled of the first instance, or None if not toggleable."""
    for o in by_type(objs).get(str(name).lower(), []):
        if o.get("toggleable"):
            return bool(o.get("isToggled"))
    return None


def starts_inside_closed(objs, name):
    """Does this object sit inside a container that is openable and closed?"""
    idx = {o["objectId"]: o for o in objs}
    for o in by_type(objs).get(str(name).lower(), []):
        for parent in (o.get("parentReceptacles") or []):
            p = idx.get(parent)
            if p and p.get("openable") and p.get("isOpen") is False:
                return True
    return False


def tags_for(row, objs):
    """Which rules a task's declared goal can trigger against this scene."""
    tags = []
    for spec in (row.get("object_states") or []):
        name = spec.get("name")
        state = spec.get("state")
        contains = spec.get("contains") or []

        # R1: something goes INTO a container that is openable and shut
        if contains and closed_openable(objs, name):
            tags.append("R1_open_before_put")

        # R2: a thing the goal needs is currently shut inside something
        for item in contains:
            if starts_inside_closed(objs, item):
                tags.append("R2_open_before_pickup")

        # R3: the goal itself demands the object be open
        if isinstance(state, str) and state.upper() == "OPENED":
            tags.append("R3_open_goal")

        # R4: goal wants a toggle state the scene is not already in
        if isinstance(state, str) and state.upper() in ("ON", "OFF"):
            now = toggled(objs, name)
            if now is not None and now != (state.upper() == "ON"):
                tags.append("R4_toggle_needed")
    return sorted(set(tags))


def floor_of(path):
    m = re.search(r"FloorPlan(\d+)", os.path.basename(path))
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/MAT2THOR")
    ap.add_argument("--manifest", default="scripts/nscc/tasks_eligible_mat2.manifest")
    ap.add_argument("--label", default="MAT2-THOR")
    args = ap.parse_args()

    rows_out, tags_out = [], []
    counts, total, no_fixture = Counter(), 0, set()

    for path in sorted(glob.glob(os.path.join(args.data, "*.json"))):
        floor = floor_of(path)
        objs = scene(floor)
        if objs is None:
            no_fixture.add(floor)
            continue
        for idx, row in enumerate(load_rows(path)):
            if row.get("_bad"):
                continue
            total += 1
            tags = tags_for(row, objs)
            if not tags:
                continue
            counts.update(tags)
            rows_out.append("%s | %s | %s" % (floor, idx, path))
            tags_out.append("%s|%s|%s|%s|%s"
                            % (floor, idx, os.path.basename(path),
                               ",".join(tags), row.get("task", "").strip()[:60]))

    hdr = [
        "# %s tasks that CAN exhibit a DAG-fixable precondition failure." % args.label,
        "# Generated by scripts/build_eligibility.py from scene metadata and the",
        "# dataset's declared goals only - no model output is consulted, so this",
        "# set is fixed before any run and cannot be shaped by what the pipeline",
        "# produced. Re-derive with:",
        "#   python scripts/build_eligibility.py --data %s --manifest %s"
        % (args.data, args.manifest),
        "#   R1 open_before_put     put X into a container that is openable AND closed",
        "#   R2 open_before_pickup  a needed object starts inside a closed container",
        "#   R3 open_goal           the goal requires an object be OPENED",
        "#   R4 toggle_needed       goal ON/OFF and the scene is in the opposite state",
        "# Per-task rule tags live alongside this file in .tags",
        "# floor | task-index | dataset",
    ]
    open(args.manifest, "w").write("\n".join(hdr + rows_out) + "\n")
    open(os.path.splitext(args.manifest)[0] + ".tags", "w").write(
        "\n".join(tags_out) + "\n")

    print("dataset        : %s (%s)" % (args.data, args.label))
    print("tasks scanned  : %d" % total)
    print("ELIGIBLE       : %d" % len(rows_out))
    for k, v in counts.most_common():
        print("   %-24s %d" % (k, v))
    if no_fixture:
        print("no fixture for floor plans: %s" % sorted(no_fixture))
    print("\nwrote %s\nwrote %s"
          % (args.manifest, os.path.splitext(args.manifest)[0] + ".tags"))


if __name__ == "__main__":
    main()

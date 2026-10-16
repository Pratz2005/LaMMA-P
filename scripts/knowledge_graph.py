
import argparse
import json
import os
import sys
from collections import defaultdict
import numpy as np
from typing import Type
from ai2thor.controller import Controller
from ai2thor.platform import CloudRendering
from scipy.spatial import distance

sys.path.append(".")
import resources.robots as robots_module


def sanitize_objects(objects: list) -> tuple[list, dict]:
    """Replace AI2-THOR objectIds (e.g. "Apple|-00.47|+01.15|+00.48") with
    legal PDDL symbols (e.g. "Apple_1").

    PDDL names must start with a letter and contain only letters, digits,
    and hyphens/underscores afterwards - the raw AI2-THOR ids contain '|',
    '.', and '+', which break the Fast Downward parser. Returns the
    rewritten object list plus an id_map (safe_name -> original objectId)
    so plans can be mapped back to real AI2-THOR objects at execution time.
    """
    counters = defaultdict(int)
    id_map = {}
    sanitized = []

    for obj in objects:
        raw_id = obj["objectId"]
        obj_type = obj.get("objectType", "Object")
        counters[obj_type] += 1
        safe_name = f"{obj_type}_{counters[obj_type]}"

        id_map[safe_name] = raw_id

        new_obj = dict(obj)
        new_obj["objectId"] = safe_name
        new_obj["objectIdRaw"] = raw_id
        sanitized.append(new_obj)

    raw_to_safe = {raw: safe for safe, raw in id_map.items()}
    for obj in sanitized:
        if obj.get("receptacleObjectIds"):
            obj["receptacleObjectIds"] = [
                raw_to_safe.get(child_id, child_id) for child_id in obj["receptacleObjectIds"]
            ]

    return sanitized, id_map


class Knowledge_Graph:
    def __init__(self, controller: Type[Controller] = None, floor_no: int = 1,
                 height: int = 1000, width: int = 1000, robots: list = None):
        # controller defaults to None: building graphs from a cached fixture
        # needs no simulator at all, and requiring one would force every
        # CPU-only run to have a GPU available.
        self.controller = controller
        self.floor_no = floor_no
        self.height = height
        self.width = width
        self.controller_instance = None
        # Only the robots actually spawned for this session should ever reach
        # the LLM - otherwise it has no way to know robot3..robot28 aren't real.
        self.robots = robots if robots is not None else robots_module.robots
        self.capability_flags = ["pickupable", "openable", "breakable", "sliceable", "toggleable", "moveable", "cookable", "dirtyable", "canFillWithLiquid", "canBeUsedUp"]
        self.state_flags = ["isOpen", "isBroken", "isCooked", "isDirty", "isFilledWithLiquid", "isSliced", "isToggled", "isUsedUp", "isPickedUp", "isHeatSource", "isColdSource"]

    def capture_metadata(self, output_dir: str, num_agents: int = 1, keep_alive: bool = False) -> str:
        """Reset an AI2-THOR scene and dump raw object + reachability metadata to JSON.

        By default this is a one-shot fixture capture (no agents beyond the one
        required to query reachable positions, no image rendering). Pass
        keep_alive=True to leave the Controller running afterwards (stored on
        self.controller_instance) so a caller can reuse the same session for
        execution instead of opening a second, unsynced one.
        """
        if self.controller is None:
            self.controller = Controller

        # On headless GPU servers (no X11/GLX), set AI2THOR_PLATFORM=CloudRendering
        # to render via EGL directly instead of the default X11-based Linux64 build.
        controller_kwargs = {"height": self.height, "width": self.width}
        if os.environ.get("AI2THOR_PLATFORM") == "CloudRendering":
            controller_kwargs["platform"] = CloudRendering

        c = self.controller(**controller_kwargs)
        c.reset(scene=f"FloorPlan{self.floor_no}")

        c.step(dict(action="Initialize", agentMode="default", snapGrid=False,
                    gridSize=0.25, rotateStepDegrees=20, visibilityDistance=5,
                    fieldOfView=90, agentCount=num_agents))

        if num_agents > 1:
            agent_position = [e.metadata["agent"]["position"] for e in c.last_event.events]
        else:
            agent_position = c.last_event.metadata["agent"]["position"]

        objects = c.last_event.metadata["objects"]

        reachable_positions_event = c.step(action="GetReachablePositions")
        reachable_positions = reachable_positions_event.metadata["actionReturn"]

        if keep_alive:
            self.controller_instance = c
        else:
            c.stop()

        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"FloorPlan{self.floor_no}_metadata.json")
        with open(out_path, "w") as f:
            json.dump({
                "floor_plan": self.floor_no,
                "agent_position": agent_position,
                "objects": objects,
                "reachable_positions": reachable_positions,
            }, f, indent=2)

        return out_path
    
    def property_graph(self, objects):
        triplets = []
        for obj in objects:
            object_id = obj["objectId"]

            for capability in self.capability_flags:
                if obj.get(capability):
                    triplets.append((object_id, "has_capability", capability))

            for state in self.state_flags:
                value = obj.get(state)
                if value is True:
                    triplets.append((object_id, state, True))
                elif state == "isOpen" and value is False and obj.get("openable"):
                    # A closed openable container blocks pickup/put on its
                    # contents, so "closed" needs a positive fact - see
                    # property_prompt.format_property_triplet. Emitting it for
                    # non-openable objects instead produced (isClosed Floor_1),
                    # (isClosed CounterTop_1) and 60-odd others per scene, which
                    # buried the handful that carry planning consequences.
                    triplets.append((object_id, state, False))

        for r in self.robots:
            for skill in r["skills"]:
                triplets.append((r["name"], "has_capability", skill))

        return triplets
    
    def relation_graph(self, objects):
        triplets = []
        for obj in objects:
            if obj.get("receptacleObjectIds"):
                obj_id = obj["objectId"]
                obj_openable = obj["openable"]
                for child_id in obj["receptacleObjectIds"]:
                    if obj_openable:
                        triplets.append((child_id, "inside", obj_id))
                    else:
                        triplets.append((child_id, 'on', obj_id))

        return triplets

    def reachibility_graph(self, agent_position, objects, reachable_positions):
        triplets = []
        reachable_positions_tuple = [(p["x"], p["z"]) for p in reachable_positions]
        for obj in objects:
            obj_id = obj["objectId"]
            obj_pos = obj["position"]
            obj_node = [obj_pos['x'], obj_pos['z']]
            distances = distance.cdist([obj_node], reachable_positions_tuple)[0]
            closest_idx = int(np.argmin(distances))
            triplets.append((obj_id, "has_location", f"location_{closest_idx}"))

        if isinstance(agent_position, list):
            for i, position in enumerate(agent_position):
                pos_node = [position["x"], position["z"]]
                pos_distances = distance.cdist([pos_node], reachable_positions_tuple)[0]
                closest_pos_idx = int(np.argmin(pos_distances))
                triplets.append((self.robots[i]["name"], "has_location", f"location_{closest_pos_idx}"))
        else:
            pos_node = [agent_position["x"], agent_position["z"]]
            pos_distances = distance.cdist([pos_node], reachable_positions_tuple)[0]
            closest_pos_idx = int(np.argmin(pos_distances))
            triplets.append((self.robots[0]["name"], "has_location", f"location_{closest_pos_idx}"))

        return triplets
    
    def build_all(self, data):
        property_triplets = self.property_graph(data["objects"])
        relation_triplets = self.relation_graph(data["objects"])
        reach_triplets = self.reachibility_graph(data["agent_position"], data["objects"], data["reachable_positions"])
        return {"property": property_triplets, "relation": relation_triplets, "reach": reach_triplets}



def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture AI2-THOR scene metadata as a fixture for knowledge-graph development.")
    parser.add_argument("--floor-plan", type=int, default=1, help="AI2-THOR floor plan number.")
    parser.add_argument("--output-dir", type=str, default="resources/kg_fixtures", help="Directory to write the fixture JSON into.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    kg = Knowledge_Graph(Controller, args.floor_plan)
    out_path = kg.capture_metadata(args.output_dir)

    with open(out_path) as f:
        data = json.load(f)

    triplets = kg.build_all(data)

    print(f"G_property: {len(triplets['property'])} triplets")
    print(f"G_relation: {len(triplets['relation'])} triplets")
    print(f"G_reach: {len(triplets['reach'])} triplets")


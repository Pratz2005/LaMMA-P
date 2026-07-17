import argparse
import json
import os
import sys
from typing import Type
from ai2thor.controller import Controller

sys.path.append(".")
import resources.robots as robots

        

class Knowledge_Graph:
    def __init__(self, controller: Type[Controller], floor_no: int, height: int = 1000, width: int = 1000):
        self.controller = controller
        self.floor_no = floor_no
        self.height = height
        self.width = width
        self.capability_flags = ["pickupable", "openable", "breakable", "sliceable", "toggleable", "moveable", "cookable", "dirtyable", "canFillWithLiquid", "canBeUsedUp"]
        self.state_flags = ["isOpen", "isBroken", "isCooked", "isDirty", "isFilledWithLiquid", "isSliced", "isToggled", "isUsedUp", "isPickedUp", "isHeatSource", "isColdSource"]

    def capture_metadata(self, output_dir: str) -> str:
        """Reset an AI2-THOR scene and dump raw object + reachability metadata to JSON.

        This is a one-shot fixture capture for offline graph-builder development —
        no agents, no movement, no image rendering.
        """
        c = self.controller(height=self.height, width=self.width)
        c.reset(scene=f"FloorPlan{self.floor_no}")

        # Single default agent is enough to query reachable positions for the scene.
        c.step(dict(action="Initialize", agentMode="default", snapGrid=False,
                    gridSize=0.25, rotateStepDegrees=20, visibilityDistance=100,
                    fieldOfView=90, agentCount=1))

        objects = c.last_event.metadata["objects"]

        reachable_positions_event = c.step(action="GetReachablePositions")
        reachable_positions = reachable_positions_event.metadata["actionReturn"]

        c.stop()

        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"FloorPlan{self.floor_no}_metadata.json")
        with open(out_path, "w") as f:
            json.dump({
                "floor_plan": self.floor_no,
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
                triplets.append((object_id, state, obj.get(state)))

        for r in robots.robots:
            for skill in r["skills"]:
                triplets.append((r["name"], "has_capability", skill))

        return triplets
    


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

    print(len(kg.property_graph(data["objects"])))

    # print(f"Wrote {len(data['objects'])} objects and {len(data['reachable_positions'])} reachable positions to {out_path}")
    # if data["objects"]:
    #     print("\nSample object (first in list):")
    #     print(json.dumps(data["objects"][0], indent=2))

import os
import time
import threading

import cv2
import numpy as np
from scipy.spatial import distance


def closest_node(node, nodes, no_robot, closest_node_location):
    """Nearest-node lookup, offset per-robot by closest_node_location so
    multiple robots heading to the same object don't crowd the same spot."""
    distances = distance.cdist([node], nodes)[0]
    dist_indices = np.argsort(distances)
    return [nodes[dist_indices[(i * 5) + closest_node_location[i]]] for i in range(no_robot)]


def distance_pts(p1, p2):
    return ((p1[0] - p2[0]) ** 2 + (p1[2] - p2[2]) ** 2) ** 0.5


class AI2ThorExecutor:
    """Drives a live AI2-THOR Controller from parsed plan actions, rendering a
    per-agent view plus a top-down view via cv2 - same visualization as the
    original ai2_thor_controller.py demo, but as a class bound to an
    already-initialized Controller (e.g. the one KGLAMP keeps alive after
    scene capture) instead of module-level globals with import-time side
    effects.
    """

    GOAL_THRESHOLD = 0.3
    STUCK_LIMIT = 15

    def __init__(self, controller, robots, reachable_positions, id_map=None, output_dir="scripts/execution_frames"):
        self.c = controller
        self.robots = robots
        self.reachable_positions_raw = list(reachable_positions)
        self.reachable_positions = [(p["x"], p["y"], p["z"]) for p in reachable_positions]
        # plan text is lowercased by Fast Downward, so look up by lowercase name
        self.id_map = {name.lower(): real_id for name, real_id in (id_map or {}).items()}
        self.output_dir = output_dir

        self.action_queue = []
        self.task_over = False
        self._img_counter = 0
        self._thread = None

    # -- name resolution ---------------------------------------------------

    def resolve_object(self, sanitized_name: str) -> str:
        """Map a sanitized PDDL object name (any case) back to its real AI2-THOR objectId."""
        real_id = self.id_map.get(sanitized_name.lower())
        if real_id is None:
            raise KeyError(f"No AI2-THOR object found for '{sanitized_name}'")
        return real_id

    def location_position(self, location_token: str) -> dict:
        """Resolve a PDDL "location_N" symbol to its real (x, y, z) via the
        reachable-positions list it was derived from in reachibility_graph."""
        index = int(location_token.split("_")[-1])
        return self.reachable_positions_raw[index]

    def robot_by_name(self, name: str) -> dict:
        for robot in self.robots:
            if robot["name"].lower() == name.lower():
                return robot
        raise KeyError(f"No robot configured with name '{name}'")

    def agent_id(self, robot: dict) -> int:
        return int(robot["name"][len("robot"):]) - 1

    # -- lifecycle -----------------------------------------------------------

    def start(self):
        for i in range(len(self.robots)):
            os.makedirs(os.path.join(self.output_dir, f"agent_{i + 1}"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "top_view"), exist_ok=True)

        # Register the top-down camera - without this, third_party_camera_frames
        # stays empty and _render() has nothing to show.
        if not self.c.last_event.events[0].third_party_camera_frames:
            event = self.c.step(action="GetMapViewCameraProperties")
            self.c.step(action="AddThirdPartyCamera", **event.metadata["actionReturn"])

        self._thread = threading.Thread(target=self._consume_queue, daemon=True)
        self._thread.start()

    def stop(self):
        self.action_queue.append({"action": "Done"})
        self.task_over = True
        if self._thread:
            self._thread.join()
        cv2.destroyAllWindows()

    def _consume_queue(self):
        while not self.task_over:
            if not self.action_queue:
                time.sleep(0.05)
                continue

            act = self.action_queue[0]
            try:
                event = self._dispatch(act)
                self._render(event)
            except Exception as exc:
                print(f"[AI2ThorExecutor] action failed: {act} -> {exc}")
            self.action_queue.pop(0)

    def _dispatch(self, act):
        action = act["action"]

        if action == "ObjectNavExpertAction":
            event = self.c.step(dict(action=action, position=act["position"], agentId=act["agent_id"]))
            next_action = event.metadata["actionReturn"]
            if next_action is not None:
                event = self.c.step(action=next_action, agentId=act["agent_id"], forceAction=True)
            return event

        if action in ("MoveAhead", "MoveBack"):
            return self.c.step(action=action, agentId=act["agent_id"])

        if action in ("RotateLeft", "RotateRight"):
            return self.c.step(action=action, degrees=act["degrees"], agentId=act["agent_id"])

        if action in ("PickupObject", "PutObject", "ToggleObjectOn", "ToggleObjectOff",
                      "OpenObject", "CloseObject", "BreakObject", "SliceObject", "CleanObject"):
            return self.c.step(action=action, objectId=act["objectId"], agentId=act["agent_id"], forceAction=True)

        if action == "Done":
            return self.c.step(action="Done")

        raise ValueError(f"Unknown low-level action: {action}")

    def _render(self, event):
        if event is None:
            return
        for i, e in enumerate(event.events):
            cv2.imshow(f"agent{i}", e.cv2img)
            path = os.path.join(self.output_dir, f"agent_{i + 1}", f"img_{self._img_counter:05d}.png")
            cv2.imwrite(path, e.cv2img)

        third_party_frames = self.c.last_event.events[0].third_party_camera_frames
        if third_party_frames:
            top_view_rgb = cv2.cvtColor(third_party_frames[-1], cv2.COLOR_BGR2RGB)
            cv2.imshow("Top View", top_view_rgb)
            cv2.imwrite(os.path.join(self.output_dir, "top_view", f"img_{self._img_counter:05d}.png"), top_view_rgb)

        cv2.waitKey(25)
        self._img_counter += 1

    # -- navigation ------------------------------------------------------

    def go_to_object(self, robot, object_id):
        obj = next(o for o in self.c.last_event.metadata["objects"] if o["objectId"] == object_id)
        center = obj["axisAlignedBoundingBox"]["center"]
        self._navigate_to(self.agent_id(robot), [center["x"], center["y"], center["z"]])

    def go_to_location(self, robot, position):
        self._navigate_to(self.agent_id(robot), [position["x"], position["y"], position["z"]])

    def _navigate_to(self, agent_id, dest_pos):
        node_offset = [0]
        crp = closest_node(dest_pos, self.reachable_positions, 1, node_offset)[0]

        dist_goal = 10.0
        stuck_count = 0

        while dist_goal > self.GOAL_THRESHOLD:
            metadata = self.c.last_event.events[agent_id].metadata
            pos = metadata["agent"]["position"]

            prev_dist = dist_goal
            dist_goal = distance_pts([pos["x"], pos["y"], pos["z"]], crp)

            if abs(dist_goal - prev_dist) < 0.2:
                stuck_count += 1
            else:
                stuck_count = 0

            if stuck_count < self.STUCK_LIMIT:
                self.action_queue.append({
                    "action": "ObjectNavExpertAction",
                    "position": dict(x=crp[0], y=crp[1], z=crp[2]),
                    "agent_id": agent_id,
                })
            else:
                node_offset[0] += 1
                stuck_count = 0
                crp = closest_node(dest_pos, self.reachable_positions, 1, node_offset)[0]

            # let the consumer thread drain the queued nav step before checking progress again
            while self.action_queue:
                time.sleep(0.05)

    # -- manipulation ------------------------------------------------------

    def pickup_object(self, robot, object_id):
        self.action_queue.append({"action": "PickupObject", "objectId": object_id, "agent_id": self.agent_id(robot)})

    def put_object(self, robot, receptacle_id):
        self.action_queue.append({"action": "PutObject", "objectId": receptacle_id, "agent_id": self.agent_id(robot)})

    def switch_on(self, robot, object_id):
        self.action_queue.append({"action": "ToggleObjectOn", "objectId": object_id, "agent_id": self.agent_id(robot)})

    def switch_off(self, robot, object_id):
        self.action_queue.append({"action": "ToggleObjectOff", "objectId": object_id, "agent_id": self.agent_id(robot)})

    def open_object(self, robot, object_id):
        self.action_queue.append({"action": "OpenObject", "objectId": object_id, "agent_id": self.agent_id(robot)})

    def close_object(self, robot, object_id):
        self.action_queue.append({"action": "CloseObject", "objectId": object_id, "agent_id": self.agent_id(robot)})

    def break_object(self, robot, object_id):
        self.action_queue.append({"action": "BreakObject", "objectId": object_id, "agent_id": self.agent_id(robot)})

    def slice_object(self, robot, object_id):
        self.action_queue.append({"action": "SliceObject", "objectId": object_id, "agent_id": self.agent_id(robot)})

    def clean_object(self, robot, object_id):
        self.action_queue.append({"action": "CleanObject", "objectId": object_id, "agent_id": self.agent_id(robot)})

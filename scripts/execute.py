import re
import sys
sys.path.append(".")
from scripts.kglamp_pipeline import KGLAMP
from scripts.ai2thor_executor import AI2ThorExecutor


def extract_plan_steps(raw_output: str) -> list[str]:
    """Pull just the action lines (e.g. "pickupobject robot1 bread_1 countertop_2")
    out of Fast Downward's raw stdout, dropping the trailing "(cost)" and every
    translator/search log line around them."""
    pattern = re.compile(r"^([a-zA-Z][\w\-]*(?:[ \t]+[\w\-]+)*)[ \t]+\(\d+\)[ \t]*$", re.MULTILINE)
    return [match.group(1).strip() for match in pattern.finditer(raw_output)]


class AI2Thor:
    def __init__(self, floor_no: int = 1, num_robots: int = 2):
        self.floor_no = floor_no
        self.kglamp = KGLAMP(floor_no, num_robots=num_robots)
        self.executor = AI2ThorExecutor(
            controller=self.kglamp.controller,
            robots=self.kglamp.robots,
            reachable_positions=self.kglamp.data["reachable_positions"],
            id_map=self.kglamp.id_map,
        )

        # Fast Downward lowercases action names in its plan output, so keys
        # here must be lowercase to match `step.split()[0]`.
        self.action_map = {
            "gotoobject": self._do_goto,
            "pickupobject": self._do_pickup,
            "putobject": self._do_put,
            "switchon": self._do_switch_on,
            "switchoff": self._do_switch_off,
            "openobject": self._do_open,
            "closeobject": self._do_close,
            "breakobject": self._do_break,
            "sliceobject": self._do_slice,
            "cleanobject": self._do_clean,
        }

    # PDDL actions carry an extra `?location` argument that the domain needs
    # for its preconditions but the real AI2-THOR action doesn't take
    # (GoToObject/PickupObject/SliceObject just need the object; PutObject
    # needs the *location* arg since that's the receptacle being targeted).
    def _do_goto(self, robot, target):
        if target.startswith("location_"):
            self.executor.go_to_location(robot, self.executor.location_position(target))
        else:
            self.executor.go_to_object(robot, self.executor.resolve_object(target))

    def _do_pickup(self, robot, obj, location):
        self.executor.pickup_object(robot, self.executor.resolve_object(obj))

    def _do_put(self, robot, obj, location):
        self.executor.put_object(robot, self.executor.resolve_object(location))

    def _do_slice(self, robot, obj, location):
        self.executor.slice_object(robot, self.executor.resolve_object(obj))

    def _do_switch_on(self, robot, obj):
        self.executor.switch_on(robot, self.executor.resolve_object(obj))

    def _do_switch_off(self, robot, obj):
        self.executor.switch_off(robot, self.executor.resolve_object(obj))

    def _do_open(self, robot, obj):
        self.executor.open_object(robot, self.executor.resolve_object(obj))

    def _do_close(self, robot, obj):
        self.executor.close_object(robot, self.executor.resolve_object(obj))

    def _do_break(self, robot, obj):
        self.executor.break_object(robot, self.executor.resolve_object(obj))

    def _do_clean(self, robot, obj):
        self.executor.clean_object(robot, self.executor.resolve_object(obj))

    def run_sim(self, task):
        _, raw_plan = self.kglamp.run(task)
        steps = extract_plan_steps(raw_plan)

        self.executor.start()
        try:
            for step in steps:
                tokens = step.split()
                action, robot_name, args = tokens[0], tokens[1], tokens[2:]

                handler = self.action_map.get(action)
                if handler is None:
                    print(f"[AI2Thor] Skipping unknown action: {step}")
                    continue

                robot = self.executor.robot_by_name(robot_name)
                handler(robot, *args)
        finally:
            self.executor.stop()

        return steps


if __name__ == "__main__":
    executor = AI2Thor()
    executor.run_sim("Make a sandwich by placing sliced bread and sliced tomato on a plate.")

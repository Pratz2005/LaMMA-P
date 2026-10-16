import json
import os
import re
import copy
import argparse
import sys
from datetime import datetime
from typing import Optional
sys.path.append(".")
from scripts.knowledge_graph import Knowledge_Graph, sanitize_objects
from scripts.goal_prompt import build_goal_prompt
from scripts.relation_prompt import build_relation_prompt
from scripts.reach_prompt import build_reach_prompt
from scripts.property_prompt import build_property_prompt
from scripts.pddl_prompt import build_pddl_prompt
from scripts.pddlrun_llmseparate import LLMHandler, FileProcessor, PDDLPlanner
import resources.robots as robots_module

# Overridable so a batch can pin the domain it was designed against without
# editing the working tree. Default is unchanged.
DOMAIN_FILE = os.environ.get("KGLAMP_DOMAIN", "resources/robot3.pddl")

# Per-stage token budgets. The old code used a single max_tokens=500 for every
# call, which silently truncates.
#
# 5_pddl is large because :objects must declare every location symbol, and a
# scene has one per reachable position - FloorPlan201 has 234. At 2048 the
# model was cut off mid-word partway through the declarations, which surfaces
# downstream as the misleading "Unbalanced parentheses in PDDL output".
# If you see that error, check finish_reason before blaming the model.
STAGE_TOKENS = {
    "1_goal": 512,
    "2_relation": 1536,
    "3_property": 1536,
    "4_reach": 1536,
    "5_pddl": 6144,
}

# Qwen's own generation_config recommends repetition_penalty 1.05. We decode
# greedily (temperature 0) for reproducibility, and greedy decoding on a 7B
# model degenerates into verbatim repetition without a penalty - we saw whole
# blocks of (on Floor_1 X) emitted twice. Keeping the penalty preserves
# determinism while suppressing the loop.
REPETITION_PENALTY = 1.05

# The served context window. max_tokens is a budget for the COMPLETION, but the
# server rejects the request if prompt + max_tokens exceeds the context:
#   400 'max_tokens' is too large: 6144 ... maximum context length is 8192
# Qwen2-7B supports 32768; serve with --max-model-len 32768 to match.
CONTEXT_LIMIT = int(os.environ.get("KGLAMP_CONTEXT_LIMIT", "32768"))
RESERVE = 512          # headroom for chat-template tokens we cannot count here


def extract_pddl_block(text: str) -> str:
    """Pull the bare `(define (problem ...) ...)` s-expression out of LLM output,
    stripping any markdown fences or explanatory prose around it."""
    fence_match = re.search(r"```(?:pddl)?\s*(.*?)```", text, re.DOTALL)
    candidate = fence_match.group(1) if fence_match else text

    start = candidate.find("(define")
    if start == -1:
        raise ValueError("No '(define ...)' block found in PDDL output")

    depth = 0
    for i in range(start, len(candidate)):
        if candidate[i] == "(":
            depth += 1
        elif candidate[i] == ")":
            depth -= 1
            if depth == 0:
                return candidate[start:i + 1].strip()

    raise ValueError("Unbalanced parentheses in PDDL output")


def load_task(dataset_path: str, index: int) -> dict:
    """Read one line of a MAT2Thor jsonl file.

    Some lines use Python's None rather than JSON null (they were written with
    str(dict)), so repair that before parsing.
    """
    with open(dataset_path) as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if index >= len(lines):
        raise IndexError(f"{dataset_path} has {len(lines)} tasks; asked for index {index}")
    return json.loads(re.sub(r":\s*None\b", ": null", lines[index]))


def resolve_robots(robot_ids: list) -> list:
    """Map dataset robot ids to robot dicts, renamed robot1..robotN.

    deepcopy is load-bearing: TaskManager.load_dataset mutates the dicts in
    resources/robots.py in place, so without it one task's renaming corrupts
    every later task in the same process.
    """
    out = []
    for i, rid in enumerate(robot_ids):
        rob = copy.deepcopy(robots_module.robots[rid - 1])
        rob["dataset_id"] = rid
        rob["name"] = f"robot{i + 1}"
        out.append(rob)
    return out


class KGLAMP:
    """Knowledge-graph-grounded PDDL generation over a local Qwen2 server.

    Two changes from the original beyond the model swap:

    * The scene can come from a cached fixture instead of a live AI2-THOR
      session. Capture needs a GPU; once the fixture exists everything else is
      CPU-only and byte-for-byte repeatable, which is what makes a
      hallucination study meaningful.
    * Robots come from the dataset row rather than being the first N entries of
      resources/robots.py. The task specifies WHICH robots are available and
      they are usually specialists; handing the LLM robot1/robot2 (all skills)
      silently changes the problem.
    """

    def __init__(self, floor_no: int = 1, output_dir: str = "resources/kg_fixtures",
                 robots: Optional[list] = None, num_robots: int = 2,
                 fixture: Optional[str] = None, base_url: Optional[str] = None,
                 model: Optional[str] = None, log_dir: Optional[str] = None):
        self.llm = LLMHandler(base_url=base_url, model=model)
        self.file_processor = FileProcessor(".")
        self.planner = PDDLPlanner(".", self.file_processor)
        self.robots = robots if robots is not None else robots_module.robots[:num_robots]
        self.floor_no = floor_no
        self.log_dir = log_dir
        self.finish_reasons = {}      # stage -> "stop" | "length"; "length" means truncated
        self.stages = {}
        if self.log_dir:
            os.makedirs(self.log_dir, exist_ok=True)

        # controller stays None unless a live capture is actually needed, so
        # importing this module never starts a simulator.
        self.kg = Knowledge_Graph(controller=None, floor_no=floor_no, robots=self.robots)
        self.controller = None

        fixture = fixture or os.path.join(output_dir, f"FloorPlan{floor_no}_metadata.json")
        if os.path.exists(fixture):
            self.out_path = fixture
            print(f"scene fixture: {fixture} (cached)")
        else:
            print(f"scene fixture: {fixture} missing - capturing from AI2-THOR")
            from ai2thor.controller import Controller
            self.kg.controller = Controller
            self.out_path = self.kg.capture_metadata(
                output_dir, num_agents=len(self.robots), keep_alive=True)
            self.controller = self.kg.controller_instance

        with open(self.out_path) as f:
            self.data = json.load(f)

        self.data["objects"], self.id_map = sanitize_objects(self.data["objects"])
        self.objects = self.data["objects"]

    def _log(self, stage: str, prompt: str, text: str) -> None:
        if not self.log_dir:
            return
        with open(os.path.join(self.log_dir, f"{stage}.prompt.txt"), "w") as f:
            f.write(prompt)
        with open(os.path.join(self.log_dir, f"{stage}.out.txt"), "w") as f:
            f.write(text)

    def ask(self, prompt, stage: Optional[str] = None):
        max_tokens = STAGE_TOKENS.get(stage, 1536) if stage else 1536
        # Clamp so prompt + completion can never exceed the context. ~3 chars
        # per token is a deliberate under-estimate of the token count, which
        # makes the clamp conservative rather than optimistic.
        est_prompt = len(prompt) // 3
        budget = CONTEXT_LIMIT - est_prompt - RESERVE
        if budget < max_tokens:
            max_tokens = max(256, budget)
            print(f"  [clamp] {stage}: max_tokens -> {max_tokens} "
                  f"(prompt ~{est_prompt} tok, context {CONTEXT_LIMIT})")
        # temperature=0 for reproducibility; an unreproducible hallucination is
        # not evidence of anything.
        resp, text = self.llm.query_model(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens, temperature=0, seed=0,
            frequency_penalty=0, repetition_penalty=REPETITION_PENALTY,
        )
        # Truncation masquerades as a model error two stages later, so record it
        # where it happens rather than inferring it from broken output.
        finish = resp.choices[0].finish_reason if resp and resp.choices else None
        used = resp.usage.completion_tokens if resp and resp.usage else -1
        self.finish_reasons[stage or "?"] = finish
        if finish == "length":
            print(f"  !! {stage} TRUNCATED at max_tokens={max_tokens} "
                  f"- raise STAGE_TOKENS[{stage!r}]")
        else:
            print(f"  {stage}: {used}/{max_tokens} tokens ({finish})")
        if stage:
            self._log(stage, prompt, text)
        return text

    def run(self, task):
        print(f"Task: {task}")
        # Set up early and fill in as we go: a caller inspecting the run after
        # extract_pddl_block raises still needs the stage outputs and the graph.
        self.stages = {}
        self.triplets = triplets = self.kg.build_all(self.data)
        if self.log_dir:
            with open(os.path.join(self.log_dir, "triplets.json"), "w") as f:
                json.dump(triplets, f, indent=2)

        goal = self.stages["goal"] = self.ask(
            build_goal_prompt(task, self.objects), "1_goal")
        print("Goal is ready")

        relation = self.stages["relation"] = self.ask(
            build_relation_prompt(goal, task, triplets["relation"]), "2_relation")
        print("Relation is ready")

        property_ = self.stages["property"] = self.ask(
            build_property_prompt(goal, task, relation, triplets["property"]), "3_property")
        print("Property is ready")

        reach = self.stages["reach"] = self.ask(
            build_reach_prompt(relation, property_, triplets["reach"]), "4_reach")
        print("Reach is ready")

        prob_pddl = self.stages["pddl_raw"] = self.ask(
            build_pddl_prompt(goal, relation, property_, reach), "5_pddl")
        print("PDDL is ready")

        clean_pddl = extract_pddl_block(prob_pddl)

        problem_dir = "resources/kglamp_problems"
        os.makedirs(problem_dir, exist_ok=True)
        problem_file = os.path.join(problem_dir, f"floorplan{self.floor_no}_problem.pddl")
        self.file_processor.write_file(problem_file, clean_pddl)

        plan_output = ""
        if os.path.exists(self.planner.planner_path):
            self.planner.run_plan(DOMAIN_FILE, problem_file)
            plan_file = problem_file.replace(".pddl", "_plan.txt")
            plan_output = self.file_processor.read_file(plan_file)
            print("Plan:\n", plan_output)
        else:
            # downward/ is an empty submodule until someone runs
            #   git submodule update --init downward && cd downward && ./build.py
            print(f"[skip] no planner at {self.planner.planner_path}; "
                  "problem PDDL generated but not solved")

        return clean_pddl, plan_output


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the KG-grounded PDDL pipeline against a local Qwen2 server.")
    parser.add_argument("--floor-plan", type=int, default=1)
    parser.add_argument("--dataset", type=str, default=None,
                        help="MAT2Thor jsonl; task text and robot list are taken from it")
    parser.add_argument("--task-index", type=int, default=0)
    parser.add_argument("--task", type=str, default=None,
                        help="explicit task text, overriding --dataset")
    parser.add_argument("--fixture", type=str, default=None,
                        help="cached scene metadata JSON; captured if absent")
    parser.add_argument("--num-robots", type=int, default=2,
                        help="only used when --dataset is not given")
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--log-dir", type=str, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    robots, task = None, args.task
    if args.dataset:
        row = load_task(args.dataset, args.task_index)
        robots = resolve_robots(row["robot list"])
        task = task or row["task"]
    if task is None:
        task = "Make a sandwich by placing sliced bread and sliced tomato on a plate."

    log_dir = args.log_dir or os.path.join(
        "logs", "kglamp",
        f"FloorPlan{args.floor_plan}_t{args.task_index}_"
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}")

    kglamp = KGLAMP(floor_no=args.floor_plan, robots=robots, num_robots=args.num_robots,
                    fixture=args.fixture, base_url=args.base_url, model=args.model,
                    log_dir=log_dir)
    pddl, plan = kglamp.run(task)

    print(pddl)
    print(f"\nartifacts in {log_dir}/")

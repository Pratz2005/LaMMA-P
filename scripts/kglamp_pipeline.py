import json
import os
import re
import argparse
import sys
sys.path.append(".")
from scripts.knowledge_graph import Knowledge_Graph, sanitize_objects
from scripts.goal_prompt import build_goal_prompt
from scripts.relation_prompt import build_relation_prompt
from scripts.reach_prompt import build_reach_prompt
from scripts.property_prompt import build_property_prompt
from scripts.pddl_prompt import build_pddl_prompt
from scripts.pddlrun_llmseparate import LLMHandler, FileProcessor, PDDLPlanner
from ai2thor.controller import Controller
import resources.robots as robots_module

DOMAIN_FILE = "resources/robot3.pddl"


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


class KGLAMP:
    def __init__(self, floor_no: int = 1, output_dir: str = "resources/kg_fixtures", num_robots: int = 2):
        self.llm = LLMHandler("api_key")
        self.file_processor = FileProcessor(".")
        self.planner = PDDLPlanner(".", self.file_processor)
        self.robots = robots_module.robots[:num_robots]
        self.kg = Knowledge_Graph(controller = Controller, floor_no=floor_no, robots=self.robots)
        self.out_path = self.kg.capture_metadata(output_dir, num_agents=num_robots, keep_alive=True)
        self.controller = self.kg.controller_instance
        with open(self.out_path) as f:
            self.data = json.load(f)

        self.data["objects"], self.id_map = sanitize_objects(self.data["objects"])
        self.objects = self.data["objects"]

    def ask(self, prompt):
        messages = [{'role': 'user', 'content': prompt}]
        _, text = self.llm.query_model(messages, 'gpt-4o', max_tokens = 500)
        return text

    def run(self, task):
        print(f"Task: {task}")
        triplets = self.kg.build_all(self.data)

        goal_prompt = build_goal_prompt(task, self.objects)
        goal = self.ask(goal_prompt)
        print("Goal is ready")
        print(goal)
        
        relation_prompt = build_relation_prompt(goal, task, triplets["relation"])
        relation = self.ask(relation_prompt)
        print("Relation is ready")
        
        property_prompt = build_property_prompt(goal, task, relation, triplets["property"])
        property_ = self.ask(property_prompt)
        print("Property is ready")
        
        reach_prompt = build_reach_prompt(relation, property_, triplets["reach"])
        reach = self.ask(reach_prompt)
        print("Reach is ready")
        
        pddl_prompt = build_pddl_prompt(goal, relation, property_, reach)
        prob_pddl = self.ask(pddl_prompt)
        print("PDDL is ready")

        clean_pddl = extract_pddl_block(prob_pddl)

        problem_dir = "resources/kglamp_problems"
        os.makedirs(problem_dir, exist_ok=True)
        problem_file = os.path.join(problem_dir, f"floorplan{self.kg.floor_no}_problem.pddl")
        self.file_processor.write_file(problem_file, clean_pddl)

        self.planner.run_plan(DOMAIN_FILE, problem_file)
        plan_file = problem_file.replace(".pddl", "_plan.txt")
        plan_output = self.file_processor.read_file(plan_file)
        print("Plan:\n", plan_output)

        return clean_pddl, plan_output

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture AI2-THOR scene metadata as a fixture for knowledge-graph development.")
    parser.add_argument("--floor-plan", type=int, default=1, help="AI2-THOR floor plan number.")
    parser.add_argument(
        "--task",
        type=str,
        default="Make a sandwich by placing sliced bread and sliced tomato on a plate.",
        help="Task for the agents to perform",
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    kglamp = KGLAMP(floor_no = args.floor_plan)
    pddl, plan = kglamp.run(args.task)

    print(pddl)



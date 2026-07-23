import json
import argparse
import sys
sys.path.append(".")
from scripts.knowledge_graph import Knowledge_Graph
from scripts.goal_prompt import build_goal_prompt
from scripts.relation_prompt import build_relation_prompt
from scripts.reach_prompt import build_reach_prompt
from scripts.property_prompt import build_property_prompt
from scripts.pddl_prompt import build_pddl_prompt
from scripts.pddlrun_llmseparate import LLMHandler
from ai2thor.controller import Controller

class KGLAMP:
    def __init__(self, floor_no: int = 1, output_dir: str = "resources/kg_fixtures"):
        self.llm = LLMHandler("api_key")
        self.kg = Knowledge_Graph(controller = Controller, floor_no=floor_no)
        self.out_path = self.kg.capture_metadata(output_dir)
        with open(self.out_path) as f:
            self.data = json.load(f)
        self.objects = self.data["objects"]

    def ask(self, prompt):
        messages = [{'role': 'user', 'content': prompt}]
        _, text = self.llm.query_model(messages, 'gpt-3.5-turbo', max_tokens = 500)
        return text

    def run(self, task):
        triplets = self.kg.build_all(self.data)

        goal_prompt = build_goal_prompt(task, self.objects)
        goal = self.ask(goal_prompt)
        print("Goal is ready")
        
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

        return prob_pddl

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture AI2-THOR scene metadata as a fixture for knowledge-graph development.")
    parser.add_argument("--floor-plan", type=int, default=1, help="AI2-THOR floor plan number.")
    parser.add_argument("--task", type=str, help="Task for the agents to perform")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    kglamp = KGLAMP(floor_no = args.floor_plan)
    pddl = kglamp.run(args.task)

    print(pddl)



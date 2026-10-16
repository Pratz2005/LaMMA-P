# PreCoNeR: Precedence-Constrained Neurosymbolic Repair (`kglamp` branch)

This branch adds **PreCoNeR** on top of a KGLAMP-style LLM-to-PDDL pipeline built on the LaMMA-P codebase and the MAT-THOR benchmark.

The PreCoNeR loop works in four steps:
1. Derive a Safety-DAG of precedence constraints from the scene knowledge graph.
2. Check every plan against it, even when the planner reports success.
3. When an edge is violated, send one narrowly scoped LLM call that proposes the missing `(:init ...)` atoms.
4. Screen those atoms (syntax, domain vocabulary, graph truth), inject the survivors, and replan.

## Files

| path | role |
|---|---|
| `scripts/kglamp_pipeline.py`, `scripts/*_prompt.py`, `scripts/knowledge_graph.py` | Upstream LLM-to-PDDL pipeline: scene → knowledge graph → five LLM stages → PDDL problem |
| `scripts/run_kg_task.py` | Runs one MAT-THOR task through the pipeline and Fast Downward |
| `scripts/safety_dag.py` | Builds the Safety-DAG from the graph and checks plans against it |
| `scripts/dag_llm_init.py` | LLM repair: prompt, reply parser, three screening passes |
| `scripts/dag_inject.py` | Injects screened atoms into `:init` and replans |
| `scripts/llmarm_trace.py`, `scripts/llmarm_sweep.py` | Repair loop on one run / across a run tree |
| `scripts/make_table4.py` | Builds `RESULTS.md` and the tables from the sweep JSON |
| `resources/robot3.pddl` | PDDL domain used in all experiments |
| `resources/kg_fixtures/` | Cached AI2-THOR scene metadata (no simulator needed to rerun) |
| `data/final_test/` | MAT-THOR tasks |
| `runs_4/` | Paper runs: prompts, raw model replies, PDDL before and after repair, plans |

### Paper Table 1 → run directories

| task | run dir | plan before → after repair |
|---|---|---|
| Task 0: FloorPlan201, watch + keychain → drawer | `runs_4/FP201_t0_easy_20260913-135949` | 9 → 10 |
| Task 1: FloorPlan15, apple → fridge, light off | `runs_4/FP15_t0_easy_20260913-130607` | 7 → 8 |
| Task 2: FloorPlan201, vase → table, open book | `runs_4/FP201_t2_easy_20260913-140115` | no plan → 7 |

`runs_4/llmarm_sweep.json` and `runs_4/RESULTS.md` hold the full sweep over the benchmark.

## Reproducing

Setup (pixi environment, Qwen2-7B-Instruct weights, Fast Downward build) is described in `SETUP.md`. All LLM calls go to a local vLLM server serving `Qwen/Qwen2-7B-Instruct` at temperature 0, seed 0.

```bash
git submodule update --init downward && (cd downward && ./build.py release)

# 1. Upstream pipeline for one task (starts vLLM, runs KG -> PDDL -> plan)
FLOOR=201 TASK=0 ./scripts/local/run_task.sh

# 2. Safety-DAG check (CPU only)
pixi run python scripts/safety_dag.py 'runs_4/FP*'

# 3. LLM repair + screening + replan on one run (needs the vLLM server)
export KGLAMP_LLM_BASE_URL=http://localhost:8000/v1 KGLAMP_MODEL=Qwen/Qwen2-7B-Instruct
pixi run python scripts/llmarm_trace.py runs_4/FP201_t0_easy_20260913-135949

# 4. Full sweep + tables (what scripts/nscc/run_batch4.pbs runs)
pixi run python scripts/llmarm_sweep.py --runs runs_4 \
    --tags scripts/nscc/tasks_all_final_test.tags --timeout 300 \
    --out runs_4/llmarm_sweep.json --resume
pixi run python scripts/make_table4.py --sweep runs_4/llmarm_sweep.json --out-dir runs_4
```

`KGLAMP_REPAIR_ATTEMPTS` (default 3) limits how many repair calls are made per violated task. The original LaMMA-P README follows.

---

# **LaMMA-P: Generalizable Multi-Agent Long-Horizon Task Allocation and Planning with LM-Driven PDDL Planner**

This is the official repository for the LaMMA-P codebase. It includes instructions for configuring and running LaMMA-P on the MAT-THOR datasets in the AI2-THOR simulator. It is accepted as a conference paper by the IEEE International Conference on Robotics and Automation (ICRA), Atlanta, 2025.


[Project Website](https://lamma-p.github.io/) | [Paper](https://arxiv.org/abs/2409.20560) | [Video](https://www.youtube.com/watch?v=1edDuJbk_uk)

<img src="docs/motivation.png" width="100%"/>

**Abstract:** Language models (LMs) possess a strong capability to comprehend natural language, making them effective in translating human instructions into detailed plans for simple robot tasks. Nevertheless, it remains a significant challenge to handle long-horizon tasks, especially in subtask identification and allocation for cooperative heterogeneous robot teams. To address this issue, we propose a Language Model-Driven Multi-Agent PDDL Planner (LaMMA-P), a novel multi-agent task planning framework that achieves state-of-the-art performance on long-horizon tasks. LaMMA-P integrates the strengths of the LMs’ reasoning capability and the traditional heuristic search planner to achieve a high success rate and efficiency while demonstrating strong generalization across tasks. Additionally, we create MAT-THOR, a comprehensive benchmark that features household tasks with two different levels of complexity based on the AI2-THOR environment. The experimental results demonstrate that LaMMA-P achieves a 105% higher success rate and 36% higher efficiency than existing LM-based multi-agent planners.

## Code Organization
Below are the details of various important directories 
- `resources/`: Contains robot definitions and PDDL domain files
- `scripts/`: Main execution scripts adapted from [SMART-LLM](https://github.com/SMARTlab-Purdue/SMART-LLM)
- `data/`: Test datasets and example tasks extended from [SMART-LLM](https://github.com/SMARTlab-Purdue/SMART-LLM)
- `downward/`: Fast Downward planner from [Fast Downward](https://github.com/aibasel/downward/)

## Datasets
The repository includes various commands and robots with different skill sets for heterogeneous robot tasks:

- Test tasks: `data/final_test/`
- Robot definitions: `resources/robots.py`
- Floor plans: Refer to [AI2Thor Demo](https://ai2thor.allenai.org/demo) for layouts

## Environment Setup
### 1. Environment Setup

Create a conda environment (or virtualenv):
```bash
conda create -n lammap python==3.9
conda activate lammap
```

Install dependencies:
```bash
pip install -r requirements.txt
```

### 2. Fast Downward Planner Setup
The project requires the [Fast Downward Planner](https://github.com/aibasel/downward/). Follow these steps to set it up:

1. Clone the Fast Downward repository as a submodule:
```bash
git submodule update --init --recursive
cd downward
```

2. Build the planner:
```bash
./build.py
```

3. Verify the installation:
```bash
./fast-downward.py --help
```

### 3. OpenAI API Setup
The code relies on OpenAI's API for LLM functionality. To set this up:

1. Create an API Key at https://platform.openai.com/
2. Create a file named `api_key.txt` in the root folder
3. Paste your OpenAI API Key in the file

## Quickstart

### 1. Generate PDDL Plans
To generate PDDL plans for tasks in AI2Thor floor plans, run:
```bash
python scripts/pddlrun_llmseparate.py --floor-plan <floor_plan_no>
```

Additional parameters:
- `--gpt-version`: Choose between 'gpt-3.5-turbo', 'gpt-4o', 'gpt-3.5-turbo-16k' (default: 'gpt-4o')
- `--prompt-decompse-set`: Set decomposition prompt set (default: 'pddl_train_task_decomposesep')
- `--prompt-allocation-set`: Set allocation prompt set (default: 'pddl_train_task_allocationsep')

The script will:
1. Decompose the high-level task into subtasks
2. Generate PDDL problem files for each subtask
3. Run the Fast Downward planner on each subtask
4. Combine the solutions into a complete plan

Output files are stored in the `logs` directory, organized by timestamp and task name.

### 2. Execute Plans in AI2Thor
To execute the generated plans in the AI2Thor environment:
Convert the target plan into code
```bash
python plantocode.py --logs-dir ./logs --validate-code

```
then, 
```bash
python scripts/execute_plan.py --command <log_folder_name>
```
Replace `<log_folder_name>` with the specific folder name in the `logs` directory containing your generated plan.

## Citation
If you find this work useful for your research, please consider citing:
```bibtex
@inproceedings{zhang2025lamma,
  title={LaMMA-P: Generalizable Multi-Agent Long-Horizon Task Allocation and Planning with LM-Driven PDDL Planner},
  author={Zhang, Xiaopan and Qin, Hao and Wang, Fuquan and Dong, Yue and Li, Jiachen},
  booktitle={2025 IEEE International Conference on Robotics and Automation (ICRA)},
  year={2025},
  organization={IEEE}
}
```

## Acknowledgement

We sincerely thank the researchers and developers for [SMART-LLM](https://github.com/SMARTlab-Purdue/SMART-LLM), [AI2THOR](https://github.com/allenai/ai2thor), and [Fast Downward](https://github.com/aibasel/downward/) for their amazing work.

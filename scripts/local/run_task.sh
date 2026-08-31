#!/usr/bin/env bash
# Ubuntu / bare-metal equivalent of scripts/nscc/run_task.pbs.
#
# No scheduler: starts vLLM, waits for it, runs one task, shuts down.
#   ./scripts/local/run_task.sh              # FloorPlan201 task 0
#   FLOOR=201 TASK=2 ./scripts/local/run_task.sh
#
# Everything cluster-specific is an environment variable with a sane default,
# so nothing here hardcodes a path the way the PBS scripts do.
set -euo pipefail
cd "$(dirname "$0")/../.."

FLOOR="${FLOOR:-201}"
TASK="${TASK:-0}"
DATASET="${DATASET:-data/final_test/FloorPlan${FLOOR}.json}"
MODEL="${MODEL:-Qwen/Qwen2-7B-Instruct}"
PORT="${PORT:-8000}"

export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
export PATH="$HOME/.pixi/bin:$PATH"
mkdir -p logs
FIXTURE="resources/kg_fixtures/FloorPlan${FLOOR}_metadata.json"

echo "=== GPU ==="
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv || {
    echo "!! no GPU"; exit 1; }

# ---------------------------------------------------------------- scene ----
if [ -f "$FIXTURE" ]; then
    echo "=== reusing $FIXTURE ==="
else
    echo "=== capturing FloorPlan${FLOOR} from AI2-THOR ==="
    # ai2thor 5.0 CloudRendering is Vulkan-based and shells out to vulkaninfo.
    # On Ubuntu: sudo apt install vulkan-tools  (or rely on the conda package).
    for icd in /usr/share/vulkan/icd.d/nvidia_icd.json \
               /etc/vulkan/icd.d/nvidia_icd.json; do
        [ -f "$icd" ] && { export VK_ICD_FILENAMES="$icd"; break; }
    done
    AI2THOR_PLATFORM=CloudRendering \
        pixi run python scripts/knowledge_graph.py --floor-plan "$FLOOR"
fi

# ----------------------------------------------------------------- vLLM ----
echo "=== starting vLLM ==="
# Sampling is set per request by the client (temperature 0, seed 0,
# repetition_penalty 1.05). Do NOT pass --generation-config vllm: it strips
# Qwen's repetition penalty and greedy decoding then loops.
pixi run -e serve vllm serve "$MODEL" \
    --port "$PORT" --max-model-len 8192 --gpu-memory-utilization 0.90 \
    > logs/vllm_local.log 2>&1 &
SERVER_PID=$!
trap 'echo "--- stopping vLLM ---"; kill $SERVER_PID 2>/dev/null || true' EXIT INT TERM

DEADLINE=$((SECONDS + 900))
until curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; do
    kill -0 "$SERVER_PID" 2>/dev/null || { echo "!! vLLM died:"; tail -40 logs/vllm_local.log; exit 1; }
    [ "$SECONDS" -ge "$DEADLINE" ] && { echo "!! timeout:"; tail -40 logs/vllm_local.log; exit 1; }
    sleep 5
done
echo "=== server up after ${SECONDS}s ==="

# ------------------------------------------------------------- pipeline ----
export KGLAMP_LLM_BASE_URL="http://localhost:${PORT}/v1"
export KGLAMP_MODEL="$MODEL"
pixi run python scripts/run_kg_task.py \
    --dataset "$DATASET" --task-index "$TASK" \
    --floor-plan "$FLOOR" --fixture "$FIXTURE"

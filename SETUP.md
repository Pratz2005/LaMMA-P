# Setup on a fresh Linux machine

## 1. Clone

    git clone <your-repo> && cd LaMMA-P
    git submodule update --init downward

## 2. pixi

    curl -fsSL https://pixi.sh/install.sh | bash
    export PATH="$HOME/.pixi/bin:$PATH"
    pixi install            # study env: python 3.9, ai2thor, openai, vulkan-tools
    pixi install -e serve   # GPU env: vllm 0.11.2 + torch 2.9 (~8 GB)

`pixi.lock` pins every version, so this reproduces the exact environment.

### If the `serve` solve fails

The pin `vllm == 0.11.2` is not arbitrary. It was chosen on a cluster with
glibc 2.28, no Rust toolchain, and a CUDA 12.8 driver:

| constraint | effect |
|---|---|
| glibc 2.28 | vllm 0.12-0.19 ship manylinux_2_31 wheels - too new |
| no cargo/rustc | vllm 0.22+ needs llguidance 1.7.x, which has no compatible wheel and falls back to a Rust source build |
| CUDA driver 12.8 | vllm 0.21 pins torch 2.11 (+cu130); a 12.8 driver cannot run cu130 |

On Ubuntu with a newer glibc and driver you MAY be able to use a newer vllm.
If you bump it, check the wheel tags of vllm AND llguidance, and confirm the
torch build matches your driver's CUDA major version (`nvidia-smi`).

## 3. Model weights

    export HF_HOME=$HOME/.cache/huggingface     # or a large disk
    pixi run -e serve hf download Qwen/Qwen2-7B-Instruct     # ~15 GB

## 4. Fast Downward

    cd downward && ./build.py release && cd ..

Needs a C++20 compiler (`std::string::starts_with`, `unordered_set::contains`).
GCC 12+ or Clang 15+. If the build fails with "no member named 'starts_with'",
your compiler is too old:

    rm -rf downward/builds/release       # the CMake cache pins the compiler
    CXX=g++-12 CC=gcc-12 ./downward/build.py release

## 5. AI2-THOR headless rendering

ai2thor 5.0's CloudRendering backend is Vulkan-based:

    sudo apt install vulkan-tools         # provides vulkaninfo
    pixi run vulkaninfo --summary         # must list your GPU

Needs the NVIDIA Vulkan ICD at /usr/share/vulkan/icd.d/nvidia_icd.json (ships
with the driver). Only required for capturing NEW scenes - the FloorPlan201
fixture is committed, so the pipeline runs without it.

## 6. Run

    ./scripts/local/run_task.sh                    # FloorPlan201 task 0
    FLOOR=201 TASK=2 ./scripts/local/run_task.sh   # the affordance case

Output lands in `logs/kgrun/FloorPlan<N>_t<TASK>_<timestamp>/` -
`run_log.txt` has the graph, all five stage outputs, the PDDL, the plan and the
findings in one file.

## Notes

* `scripts/nscc/*.pbs` are for the NSCC PBS cluster and are not used here.
* No OpenAI key is needed. Everything goes to the local vLLM server.
* Sampling is fixed at temperature 0, seed 0, repetition_penalty 1.05, so runs
  are byte-identical. Do NOT start vLLM with `--generation-config vllm`: it
  strips Qwen's repetition penalty and greedy decoding then degenerates into
  verbatim loops.

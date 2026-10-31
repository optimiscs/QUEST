"""Wait for the specified evaluation, then run a real longest-example LoRA smoke test.

Switch to QLoRA only on an explicit CUDA out-of-memory error. All other errors
stop the workflow. The run directory retains independent logs and receipts.
"""
import argparse
import fcntl
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/strict-reproduction/quest27b-lora32k-posteval-20261031-r1"
EVAL = ROOT / "workspace/strict-reproduction/browsecomp-pro6000-nvfp4-embedding-128-20261031-r1"
ENV = ROOT / "workspace/envs/llamafactory-v095-qlora"
LF = ROOT / "workspace/strict-reproduction/llamafactory-v095-qlora32k-20261027-r1/LlamaFactory"
OOM = re.compile(r"(?:torch\.(?:cuda\.)?OutOfMemoryError|CUDA out of memory)", re.I)


def record(status, **extra):
    info = {"status": status, "epoch": time.time(), **extra}
    target = RUN / "checks/workflow-status.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    temp.replace(target)
    print(json.dumps(info, ensure_ascii=False), flush=True)


def proc_alive(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat[stat.rfind(")") + 2 :].split()[0] not in ("Z", "X")
    except (OSError, IndexError):
        return False


def evaluation_done():
    state = json.loads((EVAL / "status.json").read_text())
    cases = state["cases"]
    if len(cases) != 128:
        raise ValueError("Evaluation case count differs from 128")
    if any(x.get("agent_state") != "terminal" or x.get("judge_state") != "scored" for x in cases.values()):
        return False
    # Check controller is finished as well, not just a transient status snapshot.
    with (EVAL / "controller.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(lock, fcntl.LOCK_UN)
    return True


def gpu_pids():
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return {int(x.strip()) for x in result.stdout.splitlines() if x.strip().isdigit()}


def stop_evaluation_server():
    # Only stop this evaluation's known server; fail closed on other GPU users.
    pid = 29419
    if not proc_alive(pid):
        if gpu_pids():
            raise RuntimeError("Evaluation server is absent but another GPU process is present")
        return
    args = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    if b"vllm.entrypoints.openai.api_server" not in args or b"--port 19251" not in args or b"Qwen3.8-27B-NVFP4" not in args:
        raise RuntimeError("Evaluation server identity changed; refusing to stop it")
    for gpu_pid in gpu_pids():
        stat = Path(f"/proc/{gpu_pid}/stat").read_text()
        parent = int(stat[stat.rfind(")") + 2 :].split()[1])
        if gpu_pid != pid and parent != pid:
            raise RuntimeError(f"Unrelated GPU process {gpu_pid} is running")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if not proc_alive(pid) and not gpu_pids():
            return
        time.sleep(2)
    raise RuntimeError("Evaluation vLLM did not release the GPU")


def command_env():
    env = dict(os.environ)
    env.update(
        CUDA_VISIBLE_DEVICES="0", PYTHONNOUSERSITE="1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1",
        HF_HOME=str(RUN / "hf-cache"), HF_DATASETS_CACHE=str(RUN / "hf-cache/datasets"),
        TMPDIR="/root/autodl-tmp/quest27tmp", TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="4",
        MKL_NUM_THREADS="4", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True",
        CUDA_HOME="/usr/local/cuda", PYTHONPATH=str(LF / "src"), PYTHONUNBUFFERED="1",
    )
    env["PATH"] = f"/usr/local/cuda/bin:{ENV / 'bin'}:" + env.get("PATH", "")
    return env


def smoke(mode):
    config = yaml.safe_load((RUN / f"configs/train-{mode}.yaml").read_text())
    output = RUN / f"smoke-{mode}-output"
    attempt = RUN / f"smoke-{mode}-attempt"
    for path in (output, attempt):
        if path.exists():
            raise RuntimeError(f"Refusing to overwrite {path}")
    attempt.mkdir()
    config.update(output_dir=str(output), tokenized_path=str(RUN / "smoke-dataset"), max_steps=1,
                  gradient_accumulation_steps=2, save_steps=1, eval_steps=1,
                  run_name=f"quest27b-{mode}-longest-smoke", report_to=[])
    cfg = RUN / f"configs/smoke-{mode}.yaml"
    cfg.write_text(yaml.safe_dump(config, sort_keys=False))
    env = command_env()
    env.update(QUEST_ATTEMPT_DIR=str(attempt), QUEST_CONFIG=str(cfg), QUEST_RESOURCE_TB=str(attempt / "tensorboard"))
    cmd = [str(ENV / "bin/torchrun"), "--standalone", "--nnodes=1", "--nproc-per-node=1", str(ROOT / "training_scripts/sft/observe_training.py")]
    log = RUN / f"logs/smoke-{mode}.log"
    record("smoke_running", mode=mode, log=str(log))
    with log.open("wb") as out:
        result = subprocess.run(cmd, cwd=LF, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    text = log.read_text(errors="replace")
    if result.returncode:
        return "oom" if OOM.search(text) else "failed"
    ckpt = output / "checkpoint-1"
    for name in ("adapter_model.safetensors", "adapter_config.json", "optimizer.pt", "scheduler.pt", "trainer_state.json"):
        if not (ckpt / name).is_file():
            raise RuntimeError(f"Smoke test missing {name}")
    state = json.loads((ckpt / "trainer_state.json").read_text())
    if state.get("global_step") != 1:
        raise RuntimeError("Smoke test did not complete an optimizer update")
    metrics = json.loads((output / "eval_results.json").read_text())
    if not math.isfinite(metrics.get("eval_loss", float("nan"))):
        raise RuntimeError("Smoke test evaluation loss is missing or non-finite")
    return "ok"


def train(mode):
    state = RUN / f"training-{mode}"
    cfg = RUN / f"configs/train-{mode}.yaml"
    env = command_env()
    cmd = [str(ENV / "bin/python"), str(ROOT / "training_scripts/sft/supervise_qlora.py"),
           "--config", str(cfg), "--state-dir", str(state), "--env-dir", str(ENV),
           "--llamafactory", str(LF), "--resource-tb", str(state / "tensorboard"), "--world-size", "1"]
    record("training_running", mode=mode, state_dir=str(state))
    with (RUN / f"logs/train-{mode}-supervisor.log").open("wb") as out:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Training supervisor exited with code {result.returncode}")
    record("training_complete", mode=mode, state_dir=str(state))


def main():
    global RUN
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--run-dir", type=Path, default=RUN)
    args = parser.parse_args()
    if args.poll_seconds < 5:
        parser.error("poll-seconds must be at least 5")
    RUN = args.run_dir.resolve(strict=True)
    with (RUN / "workflow.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record("waiting_for_evaluation_and_dataset")
        while True:
            if (RUN / "STOP").exists():
                record("stopped")
                return
            report = RUN / "checks/dataset-lengths.json"
            prep_pid_file = RUN / "checks/preprocess.pid"
            if not report.exists() and prep_pid_file.exists():
                prep_pid = int(prep_pid_file.read_text().strip())
                if not proc_alive(prep_pid):
                    raise RuntimeError("Dataset preprocessing stopped without a length report")
            if report.exists() and evaluation_done():
                break
            time.sleep(args.poll_seconds)
        record("evaluation_complete")
        stop_evaluation_server()
        mode = "bf16-lora"
        result = smoke(mode)
        if result == "oom":
            record("bf16_lora_oom", fallback="qlora")
            mode = "qlora"
            result = smoke(mode)
        if result != "ok":
            raise RuntimeError(f"{mode} smoke test {result}; training not started")
        record("smoke_passed", mode=mode)
        if (RUN / "STOP").exists():
            record("stopped")
            return
        train(mode)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        record("failed", error_type=type(exc).__name__, error=str(exc))
        raise

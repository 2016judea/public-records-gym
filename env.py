"""Public Records Gym as a HUD environment (HUD SDK v6).

The agent gets the gym's seven tools as one MCP capability ("tools"), served by
gym/mcp_server.py over streamable HTTP inside the environment. One template,
`solve`, takes a task id: the prompt is read from tasks/<split>.jsonl and the
reward comes from gym/grader.py against answer_keys/<split>.jsonl.

The answer never travels in the task row: a Task carries only the id, so a
taskset synced to hud.ai shows prompts and metadata, never keys. The image
(Dockerfile.hud + .dockerignore) carries the TRAIN keys only; the held-out test
keys never leave this repo.

    hud serve env.py                       # serve on tcp://127.0.0.1:8765
    uv run python -m scripts.hud_smoke     # one train task end to end, no model spend
    hud eval hud_tasks.py claude --all     # a real model (needs a provider or HUD key)
"""
import asyncio
import json
import os
import socket

from hud import Environment
from hud.capabilities import Capability

from gym import grader
from gym.mcp_server import mcp as gym_mcp

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("GYM_MCP_PORT", "8040"))
INSTRUCTIONS = (
    "You have tools over a frozen snapshot of Minnesota public records. Use the tools to compute the "
    "answer; do not guess. Read list_layers first if you need field names, and layer_notes before you "
    "trust a layer. When done, end your reply with one line: FINAL: <answer> (a number, an ID, a JSON "
    "list of IDs, or a JSON object, as the question asks)."
)

env = Environment(name="public-records-gym", version="0.3.0")


def _load(split):
    tasks = {t["id"]: t for t in map(json.loads, open(os.path.join(ROOT, "tasks", f"{split}.jsonl")))}
    kpath = os.path.join(ROOT, "answer_keys", f"{split}.jsonl")
    keys = {k["task_id"]: k for k in map(json.loads, open(kpath))} if os.path.exists(kpath) else {}
    return tasks, keys


def final_answer(text):
    """Everything after the last FINAL:, as scripts/baseline.py reads it. No FINAL: grades the whole reply."""
    if not text:
        return None
    return text.rsplit("FINAL:", 1)[1].strip().strip("`*").strip() if "FINAL:" in text else text.strip()


def _listening(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@env.initialize
async def _start_tools():
    # One tools server per process, left up until the process exits. The server is read-only and
    # stateless, so episodes sharing it cannot leak into each other. (LocalRuntime re-imports this
    # file per acquisition while gym.mcp_server stays cached, and uvicorn holds the port after a
    # cancel, so a stop-and-restart per episode fails to bind.)
    if not _listening(PORT):
        gym_mcp.settings.host, gym_mcp.settings.port = "127.0.0.1", PORT
        gym_mcp._server_task = asyncio.create_task(gym_mcp.run_streamable_http_async())
        for _ in range(200):
            if _listening(PORT):
                break
            await asyncio.sleep(0.05)
    env.add_capability(Capability.mcp(name="tools", url=f"http://127.0.0.1:{PORT}/mcp"))


@env.template(id="solve", description="One Public Records Gym task, graded deterministically against its key.")
async def solve(task_id: str, split: str = "train"):
    tasks, keys = _load(split)
    task = tasks[task_id]
    if task_id not in keys:
        raise RuntimeError(f"no answer key for {task_id} in this image ({split} keys are not shipped)")
    answer = yield f"{INSTRUCTIONS}\n\n{task['prompt']}"
    raw = getattr(answer, "raw", answer)
    g = grader.grade(task["grader"], keys[task_id]["answer"], final_answer(raw if isinstance(raw, str) else str(raw)))
    yield float(g["reward"])

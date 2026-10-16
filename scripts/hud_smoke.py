"""Run train tasks end to end under the HUD SDK with no model spend.

Two scripted agents drive the real environment (env.py) through HUD's own run loop:
- ReplayAgent replays scripts/reference_solutions.py, with every tool call sent over
  the env's MCP capability (not to gym.tools directly), then submits FINAL: <answer>.
  It reads only the template NAME from the key file, to pick which solver to replay;
  every number it submits came back from a tool call.
- ZeroAgent submits "FINAL: 0" without touching a tool, to show the grader pays 0.

    uv run python -m scripts.hud_smoke                 # first train task
    uv run python -m scripts.hud_smoke all             # all 15
    GYM_HUD_RUNTIME=tcp://127.0.0.1:8765 uv run python -m scripts.hud_smoke all   # against `hud serve`
"""
import asyncio
import json
import os
import sys

os.environ.setdefault("HUD_TELEMETRY_ENABLED", "false")

from hud import LocalRuntime  # noqa: E402
from hud.eval import Runtime  # noqa: E402
from hud.agents.base import Agent  # noqa: E402

from scripts import reference_solutions as ref  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE = {k["task_id"]: k["template"] for k in map(json.loads, open(os.path.join(ROOT, "answer_keys/train.jsonl")))}
PROMPT_TO_ID = {t["prompt"]: t["id"] for t in map(json.loads, open(os.path.join(ROOT, "tasks/train.jsonl")))}


class ReplayAgent(Agent):
    async def __call__(self, run):
        tools = await run.client.open("tools")
        loop = asyncio.get_running_loop()
        calls = []

        def T(name, **args):  # the reference solver's tool hook, routed over MCP
            calls.append(name)
            res = asyncio.run_coroutine_threadsafe(tools.call_tool(name, args), loop).result()
            out = json.loads(res.content[0].text)
            if isinstance(out, dict) and "error" in out:
                raise RuntimeError(out["error"])
            return out

        prompt = run.prompt_text.split("\n\n", 1)[1]
        task_id = PROMPT_TO_ID[prompt]
        ref.T = T
        got = await asyncio.to_thread(ref.solve, {"prompt": prompt, "template": TEMPLATE[task_id]})
        run.trace.content = f"Used {len(calls)} tool calls.\nFINAL: {json.dumps(got)}"


class ZeroAgent(Agent):
    async def __call__(self, run):
        run.trace.content = "FINAL: 0"


async def main(which="first"):
    from hud_tasks import tasks

    chosen = tasks if which == "all" else tasks[:1]
    # GYM_HUD_RUNTIME=tcp://127.0.0.1:8765 drives an env already up under `hud serve` (the image CMD)
    url = os.environ.get("GYM_HUD_RUNTIME")
    rt = Runtime(url) if url else LocalRuntime(os.path.join(ROOT, "env.py"))
    rows = []
    for agent in (ReplayAgent(), ZeroAgent()):
        for t in chosen:
            job = await t.run(agent, runtime=rt)
            r = job.runs[0] if getattr(job, "runs", None) else None
            reward = job.reward if r is None else r.reward
            tail = (r.trace.content or "")[-80:].replace("\n", " | ") if r is not None else ""
            rows.append((type(agent).__name__, t.slug, reward))
            print(f"{type(agent).__name__:12s} {t.slug}  reward={reward}  {tail}", flush=True)
    for name in ("ReplayAgent", "ZeroAgent"):
        rs = [x[2] for x in rows if x[0] == name]
        print(f"{name}: mean reward {sum(rs) / len(rs):.3f} over {len(rs)} task(s)")


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))

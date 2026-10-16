"""The HUD taskset: every train task as a row of env.py's `solve` template.

Only the train split is listed. Its keys ship in the image so the platform can
grade; the held-out test split stays in this repo, keys and all.

    hud sync tasks public-records-gym-train
"""
import json
import os

from env import solve

ROOT = os.path.dirname(os.path.abspath(__file__))



def _rows():
    # built in a function: Taskset.from_file collects every module-level Task, so a loop
    # variable left at module scope would sync the last task twice
    out = []
    for t in map(json.loads, open(os.path.join(ROOT, "tasks", "train.jsonl"))):
        task = solve(task_id=t["id"], split="train")
        task.slug = t["id"]
        task.columns = {"tier": t["tier"], "layers": ",".join(t["layers"]), "skills": ",".join(t["skills"]),
                        "answer_type": t["answer_type"], "min_tool_calls": t["min_tool_calls"],
                        "snapshot": t["snapshot"]}
        task.agent_config = {"max_steps": 60}
        out.append(task)
    return out


tasks = _rows()

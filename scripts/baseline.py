"""Baseline: a Claude model attempts tasks through the MCP harness, graded by the
deterministic grader. Episodes (tool trace + final answer + reward) go to
baselines/<model>/<task_id>.json.

    uv run python -m scripts.baseline train 5            # first 5 train tasks, one per template
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys

from gym import grader

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODEL = os.environ.get("GYM_MODEL", "sonnet")
SYS = ("You are an analyst with tools over a frozen snapshot of Minnesota public records. Use the tools "
       "to compute the answer; do not guess. Read list_layers first if you need field names. When done, "
       "end your reply with one line: FINAL: <answer> (a number, an ID, or a JSON list of IDs).")


def run(task, outdir):
    trace = os.path.join(outdir, task["id"] + ".trace.jsonl")
    if os.path.exists(trace):
        os.remove(trace)
    cfg = {"mcpServers": {"gym": {"command": os.path.join(ROOT, ".venv/bin/python"), "args": ["-m", "gym.mcp_server"],
                                  "env": {"GYM_TRACE": trace, "PYTHONPATH": ROOT}}}}
    cfg_path = os.path.join(outdir, task["id"] + ".mcp.json")
    json.dump(cfg, open(cfg_path, "w"))
    r = subprocess.run(["claude", "-p", "--model", MODEL, "--tools", "", "--strict-mcp-config", "--mcp-config", cfg_path,
                        "--allowedTools", "mcp__gym__list_layers,mcp__gym__query_layer,mcp__gym__query_near,"
                                          "mcp__gym__geocode,mcp__gym__parcel_lookup",
                        "--system-prompt", SYS, "--max-turns", "40", "--output-format", "json", task["prompt"]],
                       capture_output=True, text=True, timeout=900, cwd="/private/tmp",
                       env={**os.environ, "ENABLE_TOOL_SEARCH": "false"})
    os.remove(cfg_path)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        res = {"result": r.stdout[-500:] + r.stderr[-500:]}
    text = res.get("result") or ""
    m = re.findall(r"FINAL:\s*(.+)", text)
    final = m[-1].strip().strip("`*") if m else None
    calls = [json.loads(l) for l in open(trace)] if os.path.exists(trace) else []
    return {"task_id": task["id"], "model": f"claude-{MODEL}", "final_answer": final, "tool_calls": len(calls),
            "tools_used": [c["tool"] for c in calls], "num_turns": res.get("num_turns"), "transcript_tail": text[-600:]}


def main(split="train", n="5"):
    tasks = [json.loads(l) for l in open(os.path.join(ROOT, f"tasks/{split}.jsonl"))]
    keys = {k["task_id"]: k for k in map(json.loads, open(os.path.join(ROOT, f"answer_keys/{split}.jsonl")))}
    # one task per template first, so a small n still spans the templates
    by_tpl, order = {}, []
    for t in tasks:
        by_tpl.setdefault(keys[t["id"]]["template"], []).append(t)
    while any(by_tpl.values()):
        for v in by_tpl.values():
            if v:
                order.append(v.pop(0))
    chosen = order[: int(n)]
    outdir = os.path.join(ROOT, "baselines", f"claude-{MODEL}")
    os.makedirs(outdir, exist_ok=True)
    with cf.ThreadPoolExecutor(5) as ex:
        eps = list(ex.map(lambda t: run(t, outdir), chosen))
    passed = 0
    for t, ep in zip(chosen, eps):
        g = grader.grade(t["grader"], keys[t["id"]]["answer"], ep["final_answer"])
        ep.update(reward=g["reward"], passed=g["passed"], template=keys[t["id"]]["template"], tier=t["tier"])
        passed += g["passed"]
        json.dump(ep, open(os.path.join(outdir, t["id"] + ".json"), "w"), indent=1)
        print(f"{t['id']} T{t['tier']} {ep['template']:28s} calls={ep['tool_calls']:3d} reward={g['reward']} "
              f"final={str(ep['final_answer'])[:50]}")
    summary = {"model": f"claude-{MODEL}", "split": split, "n": len(chosen), "passed": passed,
               "pass_rate": passed / len(chosen), "mean_tool_calls": sum(e["tool_calls"] for e in eps) / len(eps)}
    json.dump(summary, open(os.path.join(outdir, f"summary_{split}.json"), "w"), indent=1)
    print(summary)


if __name__ == "__main__":
    main(*sys.argv[1:])

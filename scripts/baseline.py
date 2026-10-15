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

INFRA = re.compile(r"session limit|rate limit|usage limit|overloaded|TIMEOUT after", re.I)
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
    try:
        r = subprocess.run(["claude", "-p", "--model", MODEL, "--tools", "", "--strict-mcp-config", "--mcp-config", cfg_path,
                        "--allowedTools", "mcp__gym__list_layers,mcp__gym__query_layer,mcp__gym__query_near,"
                                          "mcp__gym__geocode,mcp__gym__parcel_lookup,mcp__gym__layer_notes,mcp__gym__calc",
                        "--system-prompt", SYS, "--max-turns", "60", "--output-format", "json", task["prompt"]],
                       capture_output=True, text=True, timeout=1500, cwd="/private/tmp",
                       env={**os.environ, "ENABLE_TOOL_SEARCH": "false", "MAX_MCP_OUTPUT_TOKENS": "100000"})
    except subprocess.TimeoutExpired:
        r = subprocess.CompletedProcess([], 1, stdout="", stderr="TIMEOUT after 1500s")
    os.remove(cfg_path)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        res = {"result": r.stdout[-500:] + r.stderr[-500:]}
    text = res.get("result") or ""
    # everything after the last FINAL:, so a JSON answer spread over lines is kept whole
    final = text.rsplit("FINAL:", 1)[1].strip().strip("`*").strip() if "FINAL:" in text else None
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

    # RESUMABLE: a graded episode on disk is kept; only missing or infra-failed ones rerun.
    # A session/rate limit is not a wrong answer -- 2026-10-15 a limit hit mid-run scored
    # 6 of 10 Sonnet tasks as failures with 0-3 tool calls. Those are retried, never graded.
    def cached(t):
        f = os.path.join(outdir, t["id"] + ".json")
        if os.path.exists(f):
            ep = json.load(open(f))
            if not ep.get("infra_error") and "final_answer" in ep and not INFRA.search(ep.get("transcript_tail", "")):
                return ep
        return None

    todo = [t for t in chosen if cached(t) is None]
    print(f"{len(chosen) - len(todo)} cached, {len(todo)} to run", flush=True)
    with cf.ThreadPoolExecutor(3) as ex:
        for t, ep in zip(todo, ex.map(lambda t: run(t, outdir), todo)):
            ep["infra_error"] = bool(INFRA.search(ep.get("transcript_tail", "")))
            g = grader.grade(t["grader"], keys[t["id"]]["answer"], ep["final_answer"])
            ep.update(reward=g["reward"], passed=g["passed"], template=keys[t["id"]]["template"], tier=t["tier"])
            json.dump(ep, open(os.path.join(outdir, t["id"] + ".json"), "w"), indent=1)
    eps = [cached(t) for t in chosen]
    done = [(t, e) for t, e in zip(chosen, eps) if e is not None]
    for t, ep in done:
        print(f"{t['id']} T{t['tier']} {ep['template']:28s} calls={ep['tool_calls']:3d} reward={ep['reward']} "
              f"final={str(ep['final_answer'])[:50]}")
    missing = [t["id"] for t, e in zip(chosen, eps) if e is None]
    passed = sum(e["passed"] for _, e in done)
    summary = {"model": f"claude-{MODEL}", "split": split, "n": len(done), "passed": passed,
               "pass_rate": round(passed / len(done), 3) if done else None,
               "mean_tool_calls": round(sum(e["tool_calls"] for _, e in done) / len(done), 1) if done else None,
               "not_run_infra_error": missing}
    json.dump(summary, open(os.path.join(outdir, f"summary_{split}.json"), "w"), indent=1)
    print(summary)
    if missing:
        sys.exit(f"{len(missing)} episodes hit an infra error (rate limit); rerun the same command to resume")


if __name__ == "__main__":
    main(*sys.argv[1:])

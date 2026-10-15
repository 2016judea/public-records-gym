"""Re-parse and re-grade saved episodes (no model calls) after a parser or grader fix."""
import json
import os
import sys

from gym import grader

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main(split="test"):
    tasks = {t["id"]: t for t in map(json.loads, open(f"{ROOT}/tasks/{split}.jsonl"))}
    keys = {k["task_id"]: k for k in map(json.loads, open(f"{ROOT}/answer_keys/{split}.jsonl"))}
    for model in sorted(os.listdir(f"{ROOT}/baselines")):
        d = f"{ROOT}/baselines/{model}"
        eps = []
        for tid in tasks:
            f = f"{d}/{tid}.json"
            if not os.path.exists(f):
                continue
            ep = json.load(open(f))
            text = ep.get("transcript_tail", "")
            if "FINAL:" in text:
                ep["final_answer"] = text.rsplit("FINAL:", 1)[1].strip().strip("`*").strip()
            g = grader.grade(tasks[tid]["grader"], keys[tid]["answer"], ep["final_answer"])
            ep.update(reward=g["reward"], passed=g["passed"])
            json.dump(ep, open(f, "w"), indent=1)
            eps.append(ep)
        s = json.load(open(f"{d}/summary_{split}.json"))
        s.update(n=len(eps), passed=sum(e["passed"] for e in eps), pass_rate=round(sum(e["passed"] for e in eps) / len(eps), 3))
        json.dump(s, open(f"{d}/summary_{split}.json", "w"), indent=1)
        print(model, s["passed"], "/", s["n"], [(e["task_id"], e["reward"]) for e in eps if not e["passed"]])


if __name__ == "__main__":
    main(*sys.argv[1:])

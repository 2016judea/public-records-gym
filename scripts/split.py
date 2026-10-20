"""Pick the shipped tasks from the candidates, split train/test, separate the keys.

Round 4 (2026-10-20): round 3's 25 tasks keep their ids and their split (the 10 held-out
test tasks are what the baseline was measured on). Every other candidate is added if:
- a model does NOT pass it without tools (scripts/no_tool_filter.py; map tasks can earn
  partial reward from priors, e.g. abstaining everywhere: recorded, not disqualifying);
- its key reproduced through the agent's own tools (scripts/reference_solutions.py);
- its answer is not a repeat of one already taken within the same template.
New tasks go to the held-out test split when md5(id) falls in the bottom fifth, so the
split is reproducible and spread across templates. Test keys go to answer_keys/test.jsonl,
which is never shipped with a sample or in the HUD image.
"""
import hashlib
import json
import os

PUBLIC = ["id", "prompt", "tier", "skills", "answer_type", "grader", "layers", "min_tool_calls", "snapshot"]
TEST_SHARE = 0.2


def _load(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


def main():
    splits = {s: _load(f"tasks/{s}.jsonl") for s in ("train", "test")}
    keys = {s: _load(f"answer_keys/{s}.jsonl") for s in ("train", "test")}
    # round 3's tasks: kept as shipped (a re-run of this script keeps whatever is already in the split files)
    have = {t["id"] for s in splits.values() for t in s}
    tpl_of = {k["task_id"]: k["template"] for s in keys.values() for k in s}
    seen = {(k["template"], json.dumps(k["answer"])) for s in keys.values() for k in s}

    cands = [json.loads(l) for l in open("answer_keys/candidates.jsonl")]
    cands.sort(key=lambda t: hashlib.md5(t["id"].encode()).hexdigest())
    added = {"train": 0, "test": 0}
    dropped = {"no_tool_pass": 0, "repeat_answer": 0, "no_reference": 0}
    for t in cands:
        if t["id"] in have:
            continue
        if "no_tool_reward" not in t or "reference_tool_calls" not in t:
            dropped["no_reference"] += 1
            continue
        if t["no_tool_reward"] >= t["grader"].get("pass_at", 1.0):
            dropped["no_tool_pass"] += 1
            continue
        key = (t["template"], json.dumps(t["answer"]))
        if key in seen:
            dropped["repeat_answer"] += 1
            continue
        seen.add(key)
        t["min_tool_calls"] = t.pop("reference_tool_calls")
        split = "test" if int(hashlib.md5(t["id"].encode()).hexdigest()[:8], 16) / 16 ** 8 < TEST_SHARE else "train"
        splits[split].append({k: t[k] for k in PUBLIC})
        keys[split].append({"task_id": t["id"], "template": t["template"], "answer": t["answer"],
                            "intermediate": t.get("intermediate"),
                            "no_tool_model": t["no_tool_model"], "no_tool_answer": t["no_tool_answer"],
                            "no_tool_reward": t["no_tool_reward"],
                            "computed_by": "gym/templates_r4.py:t_" + t["template"]})
        tpl_of[t["id"]] = t["template"]
        added[split] += 1
    for name in ("train", "test"):
        with open(f"tasks/{name}.jsonl", "w") as f:
            for t in splits[name]:
                f.write(json.dumps({k: t[k] for k in PUBLIC}) + "\n")
        with open(f"answer_keys/{name}.jsonl", "w") as f:
            for k in keys[name]:
                f.write(json.dumps(k) + "\n")
        print(name, len(splits[name]), f"(+{added[name]})")
    print("dropped", dropped)


if __name__ == "__main__":
    main()

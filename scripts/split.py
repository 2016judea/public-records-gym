"""Pick the shipped 25 from the candidates, split train/test, separate the keys.

Drops: any candidate a model PASSES without tools (map tasks can earn partial
reward from priors, e.g. abstaining everywhere; that is recorded, not disqualifying); a repeat of an answer already taken
within the same template (diversity). Picks per template in md5 order, so the
selection is reproducible. Test split is held out: its keys go to
answer_keys/test.jsonl, which is never shipped with a sample.
"""
import hashlib
import json
import os

QUOTA = {"fees_two_cities": 4, "sales_ratio_median": 3, "chain": 3, "ratio_parcels_assessed": 5,
         "food_code_overlap": 5, "permits_30_days": 5}
TEST_PER_TEMPLATE = {"fees_two_cities": 2, "sales_ratio_median": 1, "chain": 1, "ratio_parcels_assessed": 2,
                     "food_code_overlap": 2, "permits_30_days": 2}  # 10 test / 15 train
PUBLIC = ["id", "prompt", "tier", "skills", "answer_type", "grader", "layers", "min_tool_calls", "snapshot"]


def main():
    cands = [json.loads(l) for l in open("answer_keys/candidates.jsonl")]
    cands.sort(key=lambda t: hashlib.md5(t["id"].encode()).hexdigest())
    picked, seen = [], set()
    for t in cands:
        key = (t["template"], json.dumps(t["answer"]))
        if t["no_tool_reward"] >= t["grader"].get("pass_at", 1.0) or key in seen:
            continue
        if sum(p["template"] == t["template"] for p in picked) >= QUOTA.get(t["template"], 0):
            continue
        seen.add(key)
        t["min_tool_calls"] = t.pop("reference_tool_calls")
        picked.append(t)
    assert len(picked) == 25, len(picked)
    os.makedirs("answer_keys", exist_ok=True)
    splits = {"train": [], "test": []}
    for tpl, k in TEST_PER_TEMPLATE.items():
        ts = [t for t in picked if t["template"] == tpl]
        splits["test"] += ts[:k]
        splits["train"] += ts[k:]
    for name, ts in splits.items():
        with open(f"tasks/{name}.jsonl", "w") as f:
            for t in ts:
                f.write(json.dumps({k: t[k] for k in PUBLIC}) + "\n")
        with open(f"answer_keys/{name}.jsonl", "w") as f:
            for t in ts:
                f.write(json.dumps({"task_id": t["id"], "template": t["template"], "answer": t["answer"],
                                    "intermediate": t.get("intermediate"),
                                    "no_tool_model": t["no_tool_model"], "no_tool_answer": t["no_tool_answer"],
                                    "no_tool_reward": t["no_tool_reward"],
                                    "computed_by": "gym/build_tasks.py:" + "t_" + t["template"]}) + "\n")
        print(name, len(ts))


if __name__ == "__main__":
    main()

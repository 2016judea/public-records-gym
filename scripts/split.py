"""Pick the shipped 25 from the candidates, split train/test, separate the keys.

Drops: any candidate with no_tool_reward > 0; a repeat of an answer already taken
within the same template (diversity). Picks per template in md5 order, so the
selection is reproducible. Test split is held out: its keys go to
answer_keys/test.jsonl, which is never shipped with a sample.
"""
import hashlib
import json
import os

QUOTA = {"sold_above_assessed": 4, "food_near_permit": 4, "code_cases_at_food_site": 4,
         "permits_near_contamination": 4, "top_sale_near_cleanup": 3, "most_violation_parcel": 3,
         "median_ratio": 3}
TEST_PER_TEMPLATE = {"sold_above_assessed": 2, "food_near_permit": 2, "code_cases_at_food_site": 1,
                     "permits_near_contamination": 1, "top_sale_near_cleanup": 2, "most_violation_parcel": 1,
                     "median_ratio": 1}  # 10 test / 15 train
PUBLIC = ["id", "prompt", "tier", "skills", "answer_type", "grader", "layers", "min_tool_calls", "snapshot"]


def main():
    cands = [json.loads(l) for l in open("answer_keys/candidates.jsonl")]
    cands.sort(key=lambda t: hashlib.md5(t["id"].encode()).hexdigest())
    picked, seen = [], set()
    for t in cands:
        key = (t["template"], json.dumps(t["answer"]))
        if t["no_tool_reward"] > 0 or key in seen:
            continue
        if sum(p["template"] == t["template"] for p in picked) >= QUOTA[t["template"]]:
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

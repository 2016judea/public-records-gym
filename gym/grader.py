"""Deterministic graders. No model in the loop. reward in [0, 1]; passed = reward >= pass_at."""
import json
import re


def _norm(x):
    return re.sub(r"[^0-9A-Z]", "", str(x).upper())


def _num(x):
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(x))
    return float(m.group(0).replace(",", "")) if m else None


def _as_set(x):
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except ValueError:
            x = re.split(r"[\s,;]+", x)
    return {_norm(v) for v in x if _norm(v)}


def grade(task_grader, answer, submitted):
    kind = task_grader["kind"]
    if submitted is None:
        return {"reward": 0.0, "passed": False}
    if kind == "exact":
        r = float(_norm(answer) == _norm(submitted))
        return {"reward": r, "passed": r == 1.0}
    if kind == "set_f1":
        a, s = _as_set(answer), _as_set(submitted)
        tp = len(a & s)
        r = 0.0 if tp == 0 else 2 * tp / (len(a) + len(s))
        return {"reward": round(r, 4), "passed": r >= task_grader.get("pass_at", 1.0),
                "precision": tp / len(s) if s else 0, "recall": tp / len(a)}
    if kind == "numeric_tol":
        v = _num(submitted)
        if v is None:
            return {"reward": 0.0, "passed": False}
        tol = max(task_grader.get("abs", 0), task_grader.get("rel", 0) * abs(float(answer)))
        r = float(abs(v - float(answer)) <= tol + 1e-9)
        return {"reward": r, "passed": r == 1.0}
    if kind == "map_f1":
        if isinstance(submitted, str):
            m = re.search(r"\{.*\}", submitted, re.S)
            try:
                submitted = json.loads(m.group(0)) if m else {}
            except ValueError:
                submitted = {}
        if not isinstance(submitted, dict):
            return {"reward": 0.0, "passed": False}
        # Keys match when one normalised key contains the other ("second half of 2025" vs
        # "the second half of 2025 (July...)"): the grade is on the values, not on copying a label.
        sub = {_norm(k): _norm(v) for k, v in submitted.items()}
        tp = 0
        for k, v in answer.items():
            nk = _norm(k)
            hit = sub.get(nk)
            if hit is None:
                cands = [sk for sk in sub if sk and (sk in nk or nk in sk)]
                hit = sub[cands[0]] if len(cands) == 1 else None
            tp += hit is not None and hit == _norm(v)
        r = 0.0 if tp == 0 else 2 * tp / (len(answer) + len(sub))
        return {"reward": round(r, 4), "passed": r >= task_grader.get("pass_at", 1.0)}
    raise ValueError(kind)

"""Deterministic graders. No model in the loop. reward in [0, 1]; passed = reward >= pass_at."""
import json
import re
from decimal import Decimal, InvalidOperation

# A plain number, with or without a currency marker and thousands separators: "$1,551,568.00", "1551568 USD", "-0.958", ".5"
_NUMBER = re.compile(r"[$\s]*(-?)[$\s]*(\d[\d,]*(?:\.\d*)?|\.\d+)\s*(?:USD|\$)?\s*", re.I)
_FIND_NUMBER = re.compile(r"-?(?:\d[\d,]*(?:\.\d*)?|\.\d+)")


def _norm(x):
    """Canonical form for comparison. A number compares as a number ("1,551,568.00" == "1551568",
    "1.5" != "15", "-5" != "5"); anything else (ids, labels, NOT_OBSERVED) as its A-Z0-9 skeleton.
    A digit string with a leading zero ("0102924310001", a parcel id) is an id, not a number."""
    s = str(x).strip()
    m = _NUMBER.fullmatch(s)
    if m:
        digits = m.group(2).replace(",", "")
        whole = digits.split(".")[0]
        if not (len(whole) > 1 and whole.startswith("0")):
            try:
                d = Decimal(digits).normalize()
                d = -d if m.group(1) and d else d  # "-0" is 0
                return format(d, "f")
            except InvalidOperation:
                pass
    return re.sub(r"[^0-9A-Z]", "", s.upper())


def _num(x):
    if isinstance(x, (int, float)):
        return float(x)
    m = _FIND_NUMBER.search(str(x))
    return float(m.group(0).replace(",", "")) if m else None


def _as_set(x):
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except ValueError:
            x = re.split(r"[\s,;]+", x)
    if isinstance(x, dict):
        x = list(x)
    elif not isinstance(x, (list, tuple, set, frozenset)):
        x = [x]  # a bare scalar ("42") is a one-element answer, not an iterable of digits
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
        if not a and not s:
            r, precision, recall = 1.0, 1.0, 1.0  # the right answer to "which parcels" can be none
        else:
            r = 0.0 if tp == 0 else 2 * tp / (len(a) + len(s))
            precision, recall = (tp / len(s) if s else 0.0), (tp / len(a) if a else 0.0)
        return {"reward": round(r, 4), "passed": r >= task_grader.get("pass_at", 1.0),
                "precision": precision, "recall": recall}
    if kind == "numeric_tol":
        target = _num(answer)
        if target is None:  # a non-numeric key (NOT_OBSERVED) on a numeric task grades as exact
            r = float(_norm(answer) == _norm(submitted))
            return {"reward": r, "passed": r == 1.0}
        v = _num(submitted)
        if v is None:
            return {"reward": 0.0, "passed": False}
        tol = max(task_grader.get("abs", 0), task_grader.get("rel", 0) * abs(target))
        r = float(abs(v - target) <= tol + 1e-9)
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

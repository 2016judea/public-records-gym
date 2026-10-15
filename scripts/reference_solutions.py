"""Solve every candidate using ONLY the agent's tools, and grade against the key.

This proves each answer key is reachable through the harness (not just by SQL
on the snapshot), and it is the audit trail a lab asks for: the minimal tool
trajectory per template. Writes the trajectory length into each task.
"""
import collections
import json
import re
import statistics
import sys

from gym import grader, tools

CALLS = []


def T(name, **a):
    CALLS.append(name)
    r = tools.call(name, a)
    if isinstance(r, dict) and "error" in r:
        raise RuntimeError(r["error"])
    return r


def page(fn, **a):
    """Pull every row of a paged tool call."""
    out, off = [], 0
    while True:
        r = T(fn, offset=off, **a)
        out += r["returned_rows"]
        if not r["more"]:
            return out
        off += len(r["returned_rows"])


def addr_city(prompt):
    m = re.search(r"metres of (.+?), (Minneapolis|Saint Paul|Bloomington|Edina|Roseville)", prompt)
    return m.group(1), m.group(2)


def solve(t):
    p, tpl = t["prompt"], t["template"]
    if tpl == "sold_above_assessed":
        a, c = addr_city(p)
        g = T("geocode", address=a, city=c)["matches"][0]
        rows = page("query_near", layer="sales", lat=g["lat"], lon=g["lon"], radius_m=600,
                    where="sale_month >= '2023-01' and arms_length and price > assessed", fields=["parcel_id"])
        return sorted({r["parcel_id"] for r in rows})
    if tpl == "food_near_permit":
        pno = re.search(r"permit (\S+) ", p).group(1)
        pr = T("query_layer", layer="permits", where=f"permit_no = '{pno}'", fields=["lat", "lon"], limit=1)["returned_rows"][0]
        rows = page("query_near", layer="food_inspections", lat=pr["lat"], lon=pr["lon"], radius_m=300,
                    where="violation_priority='Priority1' and inspection_date between '2025-01-01' and '2025-12-31'",
                    fields=["facility_id"])
        return collections.Counter(r["facility_id"] for r in rows).most_common(1)[0][0]
    if tpl == "code_cases_at_food_site":
        biz = re.search(r'"(.+?)"', p).group(1).replace("'", "''")
        f = T("query_layer", layer="food_inspections", where=f"business = '{biz}'", fields=["parcel_id"], limit=1)["returned_rows"][0]
        return T("query_layer", layer="code_inspections",
                 where=f"parcel_id = '{f['parcel_id']}' and completed >= '2023-01-01'", count_only=True)["total"]
    if tpl == "permits_near_contamination":
        site = re.search(r'"(.+?)"', p).group(1).replace("'", "''")
        s = T("query_layer", layer="contamination", where=f"site = '{site}'", fields=["lat", "lon"])["returned_rows"][0]
        rows = page("query_near", layer="permits", lat=s["lat"], lon=s["lon"], radius_m=300,
                    where="city='Saint Paul' and issued between DATE '2024-01-01' and DATE '2024-12-31'", fields=["permit_no"])
        return len({r["permit_no"] for r in rows})
    if tpl == "top_sale_near_cleanup":
        biz = re.search(r'"(.+?)"', p).group(1).replace("'", "''")
        f = T("query_layer", layer="food_inspections", where=f"business = '{biz}'", fields=["lat", "lon"], limit=1)["returned_rows"][0]
        s = T("query_near", layer="contamination", lat=f["lat"], lon=f["lon"], radius_m=5000,
              where="status='open' and kind like '%cleanup%'", fields=["site", "lat", "lon"], limit=1)["returned_rows"][0]
        rows = page("query_near", layer="sales", lat=s["lat"], lon=s["lon"], radius_m=500,
                    where="arms_length and sale_month >= '2022-01'", fields=["parcel_id", "price"])
        return max(rows, key=lambda r: (r["price"], [-ord(ch) for ch in r["parcel_id"]]))["parcel_id"]
    if tpl == "most_violation_parcel":
        a = re.search(r"of (.+?), Minneapolis", p).group(1)
        g = T("geocode", address=a, city="Minneapolis")["matches"][0]
        rows = page("query_near", layer="code_inspections", lat=g["lat"], lon=g["lon"], radius_m=250,
                    where="result='VS' and completed >= '2024-01-01' and parcel_id is not null", fields=["parcel_id"])
        return collections.Counter(r["parcel_id"] for r in rows).most_common(1)[0][0]
    if tpl == "median_ratio":
        a, c = addr_city(p)
        g = T("geocode", address=a, city=c)["matches"][0]
        rows = page("query_near", layer="sales", lat=g["lat"], lon=g["lon"], radius_m=1000,
                    where="arms_length and assessed > 0 and sale_month >= '2023-01'", fields=["price", "assessed"])
        return round(statistics.median(r["price"] / r["assessed"] for r in rows), 3)
    raise ValueError(tpl)


def main(path):
    tasks = [json.loads(l) for l in open(path)]
    ok = 0
    for t in tasks:
        CALLS.clear()
        try:
            got = solve(t)
            g = grader.grade(t["grader"], t["answer"], got)
        except Exception as e:
            got, g = repr(e), {"passed": False}
        t["reference_tool_calls"] = len(CALLS)
        ok += g["passed"]
        if not g["passed"]:
            print("FAIL", t["id"], t["template"], "key", t["answer"], "got", got)
    with open(path, "w") as f:
        for t in tasks:
            f.write(json.dumps(t) + "\n")
    print(f"reference solver: {ok}/{len(tasks)} keys reproduced through the tools")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "answer_keys/candidates.jsonl")

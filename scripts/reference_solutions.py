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


def addr_city(prompt):
    m = re.search(r"metres of (.+?), (Minneapolis|Saint Paul|Bloomington|Edina|Roseville)", prompt)
    return m.group(1), m.group(2)


SPELL = {"AVE": "Avenue", "ST": "Street", "BLVD": "Boulevard", "PKWY": "Parkway", "RD": "Road", "DR": "Drive",
         "PL": "Place", "LN": "Lane", "CT": "Court", "N": "North", "S": "South", "E": "East", "W": "West"}


def address_variants(addr):
    """What an agent tries when geocode misses: drop the unit and city, re-space 'NE', spell words out."""
    a = re.sub(r",.*$", "", addr.upper())
    a = re.sub(r"\s*(#|\bSTE\b|\bSUITE\b|\bUNIT\b|\bAPT\b).*$", "", a).strip()
    a = re.sub(r"\bAVENUE\b", "AVE", a)
    out = [addr, a, re.sub(r"\b([NS])([EW])$", r"\1 \2", a)]
    out.append(" ".join(SPELL.get(w, w.title() if not w[0].isdigit() else w.lower()) for w in a.split()))
    return list(dict.fromkeys(out))


def resolve_licence(biz, city):
    lic = T("query_layer", layer="licences", where=f"business = '{biz}'", fields=["address", "city"])
    addr = lic["rows"][0][0]
    for v in address_variants(addr):
        m = T("geocode", address=v, city=city)["matches"]
        exact = [x for x in m if x["address"].upper() == v.upper()]
        if len(exact) == 1:
            return exact[0]
        if len(m) == 1:
            return m[0]
    raise RuntimeError(f"unresolved {addr}")


def rows(fn, **a):
    """Pull every row of a paged tool call (2,000 per page)."""
    out, off = [], 0
    while True:
        r = T(fn, offset=off, **a)
        out += [dict(zip(r["fields"], x)) for x in r["rows"]]
        if not r["more"]:
            return out
        off += len(r["rows"])


def nearest_cleanup(lat, lon):
    for radius in (500, 1500, 5000):
        r = T("query_near", layer="contamination", lat=lat, lon=lon, radius_m=radius,
              where="status='open' and kind like '%cleanup%'", fields=["site", "lat", "lon"], limit=1)
        if r["rows"]:
            return dict(zip(r["fields"], r["rows"][0]))


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def month_window(w):
    m = re.fullmatch(r"(\w+) (\d{4})", w)
    if not m or m.group(1) not in MONTHS:
        return None
    mo, y = MONTHS.index(m.group(1)) + 1, int(m.group(2))
    return f"{y}-{mo:02d}-01", f"{y + (mo == 12)}-{mo % 12 + 1:02d}-01"


def solve(t):
    p, tpl = t["prompt"], t["template"]
    if tpl == "sales_ratio_median":
        county, start = re.search(r"sales in (\w+) County from (\w+ \d{4}) onward", p).groups()
        a, _ = month_window(start)
        T("layer_notes", layer="sales")  # multi_parcel_deed: the price is the whole deal's
        rs = rows("query_layer", layer="sales", fields=["price", "assessed"],
                  where=f"county = '{county}' and arms_length and assessed > 0 and sale_month >= '{a[:7]}' "
                        f"and multi_parcel_deed is not true")  # null = not flagged
        ratios = [r["price"] / r["assessed"] for r in rs]
        return round(T("calc", expression=f"median({ratios})")["result"], 3)
    if tpl == "messy_set":
        out = []
        for biz, city in re.findall(r'"(.+?)" \((Minneapolis|Saint Paul)\)', p):
            out.append(resolve_licence(biz.replace("'", "''"), city)["parcel_id"])
        return sorted(out)
    if tpl == "licence_coverage":
        typ = re.search(r"many '(.+?)' licences", p).group(1)
        cities = re.search(r"these cities -- (.+?) -- how", p).group(1).split(", ")
        T("layer_notes", layer="licences")  # the city registers stop at the Minneapolis and Saint Paul lines
        covered = {r[0] for r in T("query_layer", layer="licences", fields=["city"], distinct=True)["rows"]}
        out = {}
        for c in cities:
            if c in ("Minneapolis", "Saint Paul"):
                out[c] = str(T("query_layer", layer="licences", where=f"city = '{c}' and type = '{typ}'", count_only=True)["total"])
            else:
                assert c not in covered
                out[c] = "NOT_OBSERVED"
        return out
    if tpl == "fees_two_cities":
        a, b = month_window(re.search(r"issued in (\w+ \d{4}),", p).group(1))
        T("layer_notes", layer="permits")  # Minneapolis: fee repeats per parcel row; Saint Paul: no fee
        win = f"issued >= DATE '{a}' and issued < DATE '{b}'"
        stp = T("query_layer", layer="permits", where=f"city='Saint Paul' and {win} and fees_usd is not null", count_only=True)["total"]
        assert stp == 0
        rs = rows("query_layer", layer="permits", fields=["permit_no", "fees_usd"], distinct=True,
                  where=f"city='Minneapolis' and {win}")
        fees = [r["fees_usd"] for r in rs if r["fees_usd"] is not None]
        return {"Minneapolis": T("calc", expression=f"sum({fees})")["result"], "Saint Paul": "NOT_OBSERVED"}
    if tpl == "permits_compare":
        T("layer_notes", layer="permits")  # Saint Paul ends 2025-06-30; Minneapolis is one row per parcel per permit
        last = T("query_layer", layer="permits", where="city='Saint Paul'", fields=["issued"], order_by="issued desc", limit=1)["rows"][0][0]
        out = {}
        for w in re.search(r"these periods -- (.+?) -- which", p).group(1).split("; "):
            win = month_window(w)
            if not win or win[1] > last:
                assert "2025" in w or "2026" in w
                out[w] = "NOT_OBSERVED"
                continue
            n = {c: T("query_layer", layer="permits", fields=["permit_no"], distinct=True, count_only=True,
                      where=f"city='{c}' and issued >= DATE '{win[0]}' and issued < DATE '{win[1]}'")["total"]
                 for c in ("Minneapolis", "Saint Paul")}
            out[w] = max(n, key=n.get)
        return out
    if tpl == "sale_history":
        T("layer_notes", layer="sales")  # one row per parcel: the LAST sale of record only
        out = {}
        for item in re.search(r"these properties -- (.+?) -- what", p).group(1).split("; "):
            addr, city = item.rsplit(", ", 1)
            g = T("geocode", address=addr, city=city)["matches"][0]
            par = T("parcel_lookup", parcel_id=g["parcel_id"], county=g["county"])["parcels"][0]
            last = par["sales"][0] if par["sales"] else None
            out[item] = str(last["price"]) if last and last["sale_month"] < "2019-01" else "NOT_OBSERVED"
        return out
    if tpl == "food_fail":
        y, nb = re.search(r"In (\d{4}), in the Minneapolis neighborhood (.+?), how", p).groups()
        nb = nb.replace("'", "''")
        T("layer_notes", layer="food_inspections")  # one row per violation; no pass/fail published
        n = T("query_layer", layer="food_inspections", fields=["inspection_id"], distinct=True, count_only=True,
              where=f"neighborhood = '{nb}' and violation_priority = 'Priority1' and year(inspection_date) = {y}")["total"]
        return {"priority1_inspections": n, "failed_inspections": "NOT_OBSERVED"}
    if tpl == "chain":
        biz = re.search(r'"(.+?)"', p).group(1).replace("'", "''")
        g = resolve_licence(biz, "Minneapolis")
        s = nearest_cleanup(g["lat"], g["lon"])
        rs = rows("query_near", layer="food_inspections", lat=s["lat"], lon=s["lon"], radius_m=400,
                  where="violation_priority='Priority1' and inspection_date between '2025-01-01' and '2025-12-31'",
                  fields=["facility_id", "violation_id"], distinct=True)
        fid = collections.Counter(r["facility_id"] for r in rs).most_common(1)[0][0]
        pid = T("query_layer", layer="food_inspections", where=f"facility_id = '{fid}'", fields=["parcel_id"],
                distinct=True)["rows"][0][0]
        T("layer_notes", layer="code_inspections")  # rows share an inspection id
        return T("query_layer", layer="code_inspections", fields=["inspection_id"], distinct=True, count_only=True,
                 where=f"parcel_id = '{pid}' and completed >= '2024-01-01'")["total"]
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

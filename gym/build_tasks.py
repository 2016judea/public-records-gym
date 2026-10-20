"""Generate task candidates and their answer keys from the frozen snapshot.

Every answer is computed here by SQL over data/snapshot.duckdb. Nothing is typed.
Anchors are picked deterministically (md5 order) and kept only when the answer is
well-posed: non-empty, a unique winner for argmax tasks, a non-trivial count.

Writes answer_keys/candidates.jsonl (prompt + key together). scripts/split.py then drops
any candidate a model answers WITHOUT tools and writes the public task files and
the hidden answer keys.
"""
import hashlib
import json
import os

import duckdb

from gym.tools import DB

OUT = os.path.join(os.path.dirname(__file__), "..", "answer_keys", "candidates.jsonl")
PER_TEMPLATE = 6  # candidates per template; ~25 survive the no-tool filter + cap


def md5order(col):
    return f"md5({col} || 'prg-v1')"


def q(con, sql, args=None):
    return con.execute(sql, args or []).fetchall()


def anchors(con, sql, n=80):
    return q(con, sql + f" limit {n}")


# ---------------------------------------------------------------- templates

def t_sold_above_assessed(con):
    """T3: spatial radius + temporal window + cross-field comparison over sales."""
    out = []
    for addr, city, lat, lon in anchors(con, f"""
            select address, city, lat, lon from parcels
            where city in ('Minneapolis','Saint Paul') and address is not null and use ilike '%commercial%'
            order by {md5order('parcel_id')}"""):
        if q(con, "select count(*) from parcels where upper(address)=upper(?) and city=?", [addr, city])[0][0] != 1:
            continue
        r = 600
        ids = sorted({x[0] for x in q(con, f"""
            select s.parcel_id from sales s where s.lat is not null and {near(lat, lon, 's')} <= {r}
              and s.sale_month >= '2023-01' and s.arms_length and s.price > s.assessed""")})
        if 3 <= len(ids) <= 10:
            out.append(dict(template="sold_above_assessed", tier=3, skills=["spatial", "temporal", "comparison"],
                prompt=(f"List the parcel IDs of every parcel within {r} metres of {addr}, {city}, MN that has an "
                        f"arms-length recorded sale (sales layer) in or after January 2023 at a price above the "
                        f"parcel's assessed value. Measure distance between parcel centroids. Answer with the set of parcel IDs."),
                answer_type="set", grader={"kind": "set_f1", "pass_at": 1.0}, answer=ids,
                layers=["parcels", "sales"], min_tool_calls=2))
        if len(out) >= PER_TEMPLATE:
            break
    return out


def near(lat, lon, alias):
    """Haversine from a fixed point to alias.lat/alias.lon — same formula the tool uses."""
    return (f"2*6371008.8*asin(sqrt(pow(sin(radians({alias}.lat-({lat}))/2),2)"
            f"+cos(radians({lat}))*cos(radians({alias}.lat))*pow(sin(radians({alias}.lon-({lon}))/2),2)))")


def t_top_sale_near_cleanup(con):
    """T4: food facility -> nearest open cleanup site -> sales in radius -> argmax price. Three layers, two hops."""
    out = []
    for fid, biz, lat, lon in anchors(con, f"""
            select facility_id, any_value(business), any_value(lat), any_value(lon) from food_inspections
            group by facility_id having count(distinct business)=1 order by {md5order('facility_id')}""", 300):
        if q(con, "select count(distinct facility_id) from food_inspections where business=?", [biz])[0][0] != 1:
            continue
        site = q(con, f"""select site, lat, lon, {near(lat, lon, 'c')} d from contamination c
                 where status='open' and kind like '%cleanup%' and lat is not null order by d, site limit 2""")
        if len(site) < 2 or site[1][3] - site[0][3] < 20:
            continue  # nearest must be unambiguous
        sname, slat, slon, _ = site[0]
        top = q(con, f"""select parcel_id, max(price) p from sales s where arms_length and sale_month >= '2022-01'
                 and {near(slat, slon, 's')} <= 500 group by 1 order by p desc, 1 limit 2""")
        if len(top) == 2 and top[0][1] > top[1][1]:
            out.append(dict(template="top_sale_near_cleanup", tier=4, skills=["spatial", "nearest", "aggregate", "multi-hop"],
                prompt=(f"Start at the Minneapolis food facility \"{biz}\". Find the open MPCA site of kind cleanup "
                        f"(kind contains 'cleanup') nearest to it. Then, among arms-length recorded sales from January "
                        f"2022 onward on parcels within 500 metres of that site, which parcel sold for the highest "
                        f"price? Answer with the parcel ID."),
                answer_type="scalar", grader={"kind": "exact"}, answer=top[0][0],
                layers=["food_inspections", "contamination", "parcels", "sales"], min_tool_calls=3,
                intermediate={"nearest_site": sname}))
        if len(out) >= PER_TEMPLATE:
            break
    return out


from gym.templates_r4 import R4_TEMPLATES  # noqa: E402

# round 1's two survivors (sold_above_assessed, top_sale_near_cleanup) retired in round 3: Sonnet 100%
# round 4 (2026-10-20): round 3's six families over a wider grid, plus sold_above_assessed_count
TEMPLATES = R4_TEMPLATES


def main():
    con = duckdb.connect(DB, read_only=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    n = 0
    with open(OUT, "w") as f:
        for t in TEMPLATES:
            got = t(con)
            print(t.__name__, len(got))
            for i, task in enumerate(got):
                task["id"] = "prg-" + hashlib.md5(task["prompt"].encode()).hexdigest()[:10]
                task["snapshot"] = "2026-10-15"
                f.write(json.dumps(task, default=str) + "\n")
                n += 1
    print("candidates", n)


if __name__ == "__main__":
    main()

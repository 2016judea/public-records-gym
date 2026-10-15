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


def t_food_near_permit(con):
    """T3: permit -> point -> food facilities in radius -> count violations per facility -> argmax."""
    out = []
    for pno, lat, lon, issued in anchors(con, f"""
            select permit_no, any_value(lat), any_value(lon), min(issued) from permits
            where city='Minneapolis' and work='NewRes' and lat is not null and issued >= DATE '2023-01-01'
            group by permit_no order by {md5order('permit_no')}"""):
        rows = q(con, f"""select facility_id, count(*) n from food_inspections f
                 where {near(lat, lon, 'f')} <= 300 and violation_priority='Priority1'
                   and inspection_date between '2025-01-01' and '2025-12-31'
                 group by 1 order by n desc, 1""")
        if len(rows) >= 3 and rows[0][1] > rows[1][1] and rows[0][1] >= 3:
            out.append(dict(template="food_near_permit", tier=3, skills=["spatial", "temporal", "aggregate", "multi-layer"],
                prompt=(f"Minneapolis building permit {pno} marks a new residential building. Among food facilities "
                        f"within 300 metres of that permit's location, which facility recorded the most Priority1 "
                        f"food-code violations with an inspection date in calendar year 2025? Answer with its facility ID."),
                answer_type="scalar", grader={"kind": "exact"}, answer=rows[0][0],
                layers=["permits", "food_inspections"], min_tool_calls=3))
        if len(out) >= PER_TEMPLATE:
            break
    return out


def t_code_cases_at_food_site(con):
    """T2: food facility -> parcel id -> code inspection count."""
    out = []
    for fid, biz, addr, pid in anchors(con, f"""
            select facility_id, any_value(business), any_value(address), any_value(parcel_id) from food_inspections
            where parcel_id is not null group by facility_id
            having count(distinct business)=1 and count(distinct parcel_id)=1
            order by {md5order('facility_id')}""", 400):
        if q(con, "select count(distinct facility_id) from food_inspections where business=?", [biz])[0][0] != 1:
            continue
        n = q(con, "select count(*) from code_inspections where parcel_id=? and completed >= '2023-01-01'", [pid])[0][0]
        if 4 <= n <= 60:
            out.append(dict(template="code_cases_at_food_site", tier=2, skills=["entity-resolution", "multi-layer", "count"],
                prompt=(f"The Minneapolis food business \"{biz}\" ({addr}) sits on a tax parcel. How many code-inspection "
                        f"records (code_inspections layer) on that same parcel have a completed date on or after "
                        f"2023-01-01? Answer with a number."),
                answer_type="number", grader={"kind": "numeric_tol", "rel": 0.0, "abs": 0}, answer=n,
                layers=["food_inspections", "code_inspections"], min_tool_calls=2))
        if len(out) >= PER_TEMPLATE:
            break
    return out


def t_permits_near_contamination(con):
    """T3: MPCA site -> parcel centroid -> permits in radius and year."""
    out = []
    for site, addr, lat, lon in anchors(con, f"""
            select site, address, lat, lon from contamination c
            where parcel_city='Saint Paul' and status='open' and lat is not null
              and (select count(*) from contamination c2 where c2.site=c.site)=1
            order by {md5order('site')}"""):
        n = q(con, f"""select count(distinct permit_no) from permits p where city='Saint Paul'
                 and issued between DATE '2024-01-01' and DATE '2024-12-31' and {near(lat, lon, 'p')} <= 300""")[0][0]
        if 8 <= n <= 150:
            out.append(dict(template="permits_near_contamination", tier=3, skills=["spatial", "temporal", "count", "multi-layer"],
                prompt=(f"The Minnesota Pollution Control Agency lists an open site named \"{site}\" in Saint Paul. "
                        f"How many distinct Saint Paul building permits (count permit numbers) were issued during "
                        f"calendar 2024 within 300 metres of that site's parcel? Answer with a number."),
                answer_type="number", grader={"kind": "numeric_tol", "rel": 0.0, "abs": 0}, answer=n,
                layers=["contamination", "parcels", "permits"], min_tool_calls=2))
        if len(out) >= PER_TEMPLATE:
            break
    return out


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


def t_most_violation_parcel(con):
    """T3: address -> radius -> code inspections -> group by parcel -> argmax."""
    out = []
    for addr, lat, lon in anchors(con, f"""
            select address, lat, lon from parcels where city='Minneapolis' and address is not null
            and use ilike '%resid%' order by {md5order('parcel_id')}""", 300):
        if q(con, "select count(*) from parcels where upper(address)=upper(?) and city='Minneapolis'", [addr])[0][0] != 1:
            continue
        rows = q(con, f"""select parcel_id, count(*) n from code_inspections c where result='VS'
                 and completed >= '2024-01-01' and {near(lat, lon, 'c')} <= 250 and parcel_id is not null
                 group by 1 order by n desc, 1 limit 2""")
        if len(rows) == 2 and rows[0][1] > rows[1][1] and rows[0][1] >= 3:
            out.append(dict(template="most_violation_parcel", tier=3, skills=["spatial", "temporal", "aggregate"],
                prompt=(f"Within 250 metres of {addr}, Minneapolis, which parcel has the most code-inspection records "
                        f"with result 'VS' completed on or after 2024-01-01? Use the inspection record's own coordinate "
                        f"for distance. Answer with the parcel ID."),
                answer_type="scalar", grader={"kind": "exact"}, answer=rows[0][0],
                layers=["parcels", "code_inspections"], min_tool_calls=3))
        if len(out) >= PER_TEMPLATE:
            break
    return out


def t_median_ratio(con):
    """T3: numeric-tolerance task — median sale/assessed ratio in a radius and window."""
    out = []
    for addr, city, lat, lon in anchors(con, f"""
            select address, city, lat, lon from parcels where city in ('Minneapolis','Saint Paul','Bloomington','Edina','Roseville')
            and address is not null and use ilike '%commercial%' order by {md5order('parcel_id')}""", 300):
        if q(con, "select count(*) from parcels where upper(address)=upper(?) and city=?", [addr, city])[0][0] != 1:
            continue
        rows = q(con, f"""select median(price*1.0/assessed), count(*) from sales s where arms_length and assessed > 0
                 and sale_month >= '2023-01' and {near(lat, lon, 's')} <= 1000""")
        med, n = rows[0]
        if med is not None and 6 <= n <= 60:
            out.append(dict(template="median_ratio", tier=3, skills=["spatial", "temporal", "statistic"],
                prompt=(f"For all arms-length recorded sales (sales layer) in or after January 2023 on parcels within "
                        f"1,000 metres of {addr}, {city}, MN, compute each sale's price divided by its assessed value. "
                        f"What is the median of those ratios? Answer with a number rounded to 3 decimals."),
                answer_type="number", grader={"kind": "numeric_tol", "rel": 0.01, "abs": 0.0}, answer=round(med, 4),
                layers=["parcels", "sales"], min_tool_calls=2))
        if len(out) >= PER_TEMPLATE:
            break
    return out


TEMPLATES = [t_sold_above_assessed, t_food_near_permit, t_code_cases_at_food_site,
             t_permits_near_contamination, t_top_sale_near_cleanup, t_most_violation_parcel, t_median_ratio]


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

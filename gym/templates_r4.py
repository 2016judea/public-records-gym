"""Round 4: the round-3 recipe, widened to hundreds of tasks.

Same rule as round 3: every trap is true in the rows and written in no layer note, or it
is a documented trap that still costs a model transcription over 2,000+ rows. Same
families as the six round-3 templates, over a wider parameter space (more windows, kinds,
counties, case types, radii), plus one new family:

  sold_above_assessed_count   two-layer join over 2,000+ sales: how many sold above the
                              PARCELS layer's assessed value. The sales layer's own
                              `assessed` disagrees on 333 rows (undocumented), and Carver
                              and Scott share 2,582 parcel ids (a join on id alone doubles)

Prompt wording for a parameter set that round 3 already used is unchanged, so round 3's
25 tasks keep their ids and their held-out split.

Every key is computed here by SQL. Nothing is typed.
"""
from gym.templates_hard import (SUFFIX, _resolvable_licences, md5order, mname, near, q)

QUARTERS = {1: "first quarter of {y} (January through March)", 2: "second quarter of {y} (April through June)",
            3: "third quarter of {y} (July through September)", 4: "fourth quarter of {y} (October through December)"}


def _cap(out, n, salt):
    """Keep at most n, chosen by md5 of the prompt (reproducible, spread across the parameter grid)."""
    import hashlib
    out.sort(key=lambda t: hashlib.md5((t["prompt"] + salt).encode()).hexdigest())
    return out[:n]


# ---- permits: completed before issued (Saint Paul, 34 rows, in no note) -------------------------

def t_permits_days(con):
    out = []
    kinds = [k for (k,) in q(con, "select distinct kind from permits where city='Saint Paul' order by 1")]
    for y in range(2020, 2026):
        for kind in kinds:
            for days in (14, 30, 60, 90):
                good, naive = q(con, f"""select count(distinct permit_no) filter (where datediff('day', issued, completed) between 0 and {days}),
                                               count(distinct permit_no) filter (where datediff('day', issued, completed) <= {days})
                                        from permits where city='Saint Paul' and year(issued)={y} and kind=?""", [kind])[0]
                if naive != good and good >= 5:
                    out.append(dict(template="permits_30_days", tier=3, skills=["date-arithmetic", "undocumented-trap", "count"],
                        prompt=(f"How many Saint Paul permits of kind '{kind}' issued in {y} were completed within {days} days "
                                f"of being issued? Answer with a number." + SUFFIX),
                        answer_type="number", grader={"kind": "numeric_tol", "abs": 0}, answer=good, layers=["permits"],
                        min_tool_calls=2, intermediate={"count_with_negative_durations": naive}))
            # quarter grain: the same trap inside a narrower window
            for qt in (1, 2, 3, 4):
                good, naive = q(con, """select count(distinct permit_no) filter (where datediff('day', issued, completed) between 0 and 30),
                                              count(distinct permit_no) filter (where datediff('day', issued, completed) <= 30)
                                       from permits where city='Saint Paul' and year(issued)=? and quarter(issued)=? and kind=?""",
                                [y, qt, kind])[0]
                if naive != good and good >= 5:
                    out.append(dict(template="permits_30_days", tier=3, skills=["date-arithmetic", "undocumented-trap", "count"],
                        prompt=(f"How many Saint Paul permits of kind '{kind}' issued in the {QUARTERS[qt].format(y=y)} were "
                                f"completed within 30 days of being issued? Answer with a number." + SUFFIX),
                        answer_type="number", grader={"kind": "numeric_tol", "abs": 0}, answer=good, layers=["permits"],
                        min_tool_calls=2, intermediate={"count_with_negative_durations": naive}))
    return _cap(out, 60, "pd")


# ---- permits: fee repeated per parcel row; Saint Paul publishes no fee ----------------------------

def t_fees_two_cities(con):
    assert q(con, "select count(fees_usd) from permits where city='Saint Paul'")[0][0] == 0
    out = []
    for m, ds, n, rs in q(con, """with r as (select strftime(issued,'%Y-%m') m, sum(fees_usd) rs from permits
                                   where city='Minneapolis' group by 1),
                             d as (select m, sum(fees_usd) ds, count(*) n from (select distinct strftime(issued,'%Y-%m') m,
                                   permit_no, fees_usd from permits where city='Minneapolis') group by 1)
                        select m, ds, n, rs from r join d using(m)
                        where n > 2000 and rs > 1.15 * ds and m <= '2025-06' order by m"""):
        out.append(dict(template="fees_two_cities", tier=4,
            skills=["aggregate", "paging", "dedup-trap", "coverage", "arithmetic"],
            prompt=(f"What was the total of the permit fees charged on building permits issued in {mname(m)}, "
                    f"for Minneapolis and for Saint Paul separately? Answer as a JSON object mapping city to USD." + SUFFIX),
            answer_type="map", grader={"kind": "map_f1", "pass_at": 1.0},
            answer={"Minneapolis": str(int(ds)), "Saint Paul": "NOT_OBSERVED"}, layers=["permits"], min_tool_calls=4,
            intermediate={"distinct_permits": n, "naive_row_sum": int(rs)}))
    for y, qt, ds, n, rs in q(con, """with r as (select year(issued) y, quarter(issued) qt, sum(fees_usd) rs from permits
                                       where city='Minneapolis' group by all),
                                 d as (select y, qt, sum(fees_usd) ds, count(*) n from (select distinct year(issued) y,
                                       quarter(issued) qt, permit_no, fees_usd from permits where city='Minneapolis') group by all)
                            select y, qt, ds, n, rs from r join d using(y, qt)
                            where rs > 1.15 * ds and (y < 2025 or (y = 2025 and qt <= 2)) order by y, qt"""):
        out.append(dict(template="fees_two_cities", tier=4,
            skills=["aggregate", "paging", "dedup-trap", "coverage", "arithmetic"],
            prompt=(f"What was the total of the permit fees charged on building permits issued in the "
                    f"{QUARTERS[qt].format(y=y)}, for Minneapolis and for Saint Paul separately? Answer as a JSON object "
                    f"mapping city to USD." + SUFFIX),
            answer_type="map", grader={"kind": "map_f1", "pass_at": 1.0},
            answer={"Minneapolis": str(int(ds)), "Saint Paul": "NOT_OBSERVED"}, layers=["permits"], min_tool_calls=6,
            intermediate={"distinct_permits": n, "naive_row_sum": int(rs)}))
    return out


# ---- sales x parcels: two assessed columns that disagree on 333 rows ------------------------------

COUNTY_SETS = [("Hennepin",), ("Ramsey",), ("Washington",), ("Scott", "Carver"), ("Hennepin", "Ramsey")]
STARTS = [None] + [f"{y}-{m}" for y in range(2008, 2024) for m in ("01", "07")]


def _where(counties, start):
    return (" and ".join(counties) + (" Counties" if len(counties) > 1 else " County"),
            f" from {mname(start)} onward" if start else "")


def t_ratio_parcels_assessed(con):
    out = []
    for counties in COUNTY_SETS:
        cl = ",".join(f"'{c}'" for c in counties)
        for start in STARTS:
            since = f"and s.sale_month >= '{start}'" if start else ""
            n, med_p, med_s = q(con, f"""select count(*), median(s.price * 1.0 / p.assessed), median(s.price * 1.0 / s.assessed)
                                        from sales s join parcels p on p.parcel_id = s.parcel_id and p.county = s.county
                                        where s.county in ({cl}) and s.arms_length and s.multi_parcel_deed is not true
                                          and p.assessed > 0 {since}""")[0]
            if not (2000 < n <= 8000) or abs(med_p - (med_s or 0)) < 0.0015:
                continue
            where, when = _where(counties, start)
            out.append(dict(template="ratio_parcels_assessed", tier=4,
                skills=["two-layer-join", "paging", "arithmetic", "undocumented-trap"],
                prompt=(f"For the arms-length recorded sales in {where}{when} whose recorded price is for that one "
                        f"parcel alone (not a price shared across several parcels on one deed), divide each sale price "
                        f"by the assessed value that the parcels layer records for that parcel. What is the median of "
                        f"those ratios? Leave out sales whose parcel has no assessed value in the parcels layer. Answer "
                        f"with a number rounded to 3 decimals." + SUFFIX),
                answer_type="number", grader={"kind": "numeric_tol", "abs": 0.0006}, answer=round(med_p, 4),
                layers=["sales", "parcels"], min_tool_calls=6,
                intermediate={"sales": n, "median_using_sales_layer_assessed": round(med_s, 4)}))
    return _cap(out, 40, "rpa")


def t_sold_above_assessed_count(con):
    out = []
    for counties in COUNTY_SETS:
        cl = ",".join(f"'{c}'" for c in counties)
        for start in STARTS:
            since = f"and s.sale_month >= '{start}'" if start else ""
            n, good, naive, idonly = q(con, f"""select count(*), count(*) filter (where s.price > p.assessed),
                                    count(*) filter (where s.price > s.assessed),
                                    (select count(*) from sales s2 join parcels p2 on p2.parcel_id = s2.parcel_id
                                      where s2.county in ({cl}) and s2.arms_length and s2.multi_parcel_deed is not true
                                        and p2.assessed > 0 and s2.price > p2.assessed {since.replace('s.', 's2.')})
                                  from sales s join parcels p on p.parcel_id = s.parcel_id and p.county = s.county
                                  where s.county in ({cl}) and s.arms_length and s.multi_parcel_deed is not true
                                    and p.assessed > 0 {since}""")[0]
            if not (2000 < n <= 8000) or good == naive:
                continue
            where, when = _where(counties, start)
            out.append(dict(template="sold_above_assessed_count", tier=4,
                skills=["two-layer-join", "paging", "comparison", "undocumented-trap"],
                prompt=(f"Consider the arms-length recorded sales in {where}{when} whose recorded price is for that one "
                        f"parcel alone (not a price shared across several parcels on one deed). How many of them sold "
                        f"for more than the assessed value that the parcels layer records for that parcel? Leave out "
                        f"sales whose parcel has no assessed value in the parcels layer. Answer with a number." + SUFFIX),
                answer_type="number", grader={"kind": "numeric_tol", "abs": 0}, answer=good,
                layers=["sales", "parcels"], min_tool_calls=6,
                intermediate={"sales": n, "count_using_sales_layer_assessed": naive, "count_joining_on_id_only": idonly}))
    return _cap(out, 40, "sac")


# ---- sales: median over 2,000+ rows; multi-parcel deeds carry the deal's price --------------------

def t_sales_ratio_median(con):
    out = []
    for county in ("Hennepin", "Ramsey", "Anoka", "Dakota", "Washington"):
        for start in [s for s in STARTS if s]:
            n, med = q(con, """select count(*), median(price * 1.0 / assessed) from sales
                              where county = ? and arms_length and assessed > 0 and sale_month >= ?
                                and not coalesce(multi_parcel_deed, false)""", [county, start])[0]
            naive = q(con, """select median(price * 1.0 / assessed) from sales where county = ? and arms_length
                              and assessed > 0 and sale_month >= ?""", [county, start])[0][0]
            if 2000 < n <= 8000 and naive is not None and abs(naive - med) > 0.002:
                out.append(dict(template="sales_ratio_median", tier=4, skills=["aggregate", "paging", "arithmetic", "filter-trap"],
                    prompt=(f"Across all arms-length recorded sales in {county} County from {mname(start)} onward, "
                            f"counting only sales whose recorded price is for that one parcel alone (not a price "
                            f"shared across several parcels on one deed), what is the median ratio of sale price to "
                            f"assessed value? Leave out parcels with no assessed value. Answer with a number rounded "
                            f"to 3 decimals." + SUFFIX),
                    answer_type="number", grader={"kind": "numeric_tol", "abs": 0.0006}, answer=round(med, 4),
                    layers=["sales"], min_tool_calls=4,
                    intermediate={"sales": n, "median_if_multi_parcel_kept": round(naive, 4)}))
    return _cap(out, 25, "srm")


# ---- food x code inspections: two slices over 2,000 rows each -------------------------------------

def t_food_code_overlap(con):
    out = []
    for prio in ("Priority1", "Priority2"):
        for y in (2023, 2024, 2025, 2026):
            for ct, label in ((None, "a code inspection"), ("FIS", "a code inspection of case type 'FIS'"),
                              ("HIS", "a code inspection of case type 'HIS'"),
                              ("Nuisance", "a code inspection of case type 'Nuisance'"),
                              ("VBR", "a code inspection of case type 'VBR'")):
                rf = f"and case_type = '{ct}'" if ct else ""
                n = q(con, f"""select count(*) from (
                        select distinct parcel_id from food_inspections where violation_priority='{prio}'
                          and year(inspection_date)={y} and parcel_id is not null
                        intersect
                        select distinct parcel_id from code_inspections where year(completed)={y} {rf})""")[0][0]
                fr = q(con, f"select count(*) from food_inspections where violation_priority='{prio}' and year(inspection_date)={y}")[0][0]
                cr = q(con, f"select count(*) from code_inspections where year(completed)={y} {rf}")[0][0]
                if n >= 10 and cr > 2000:
                    out.append(dict(template="food_code_overlap", tier=4, skills=["two-layer-join", "paging", "set-ops"],
                        prompt=(f"How many distinct tax parcels in Minneapolis had both at least one {prio} food-code "
                                f"violation on an inspection dated in {y} and {label} completed in {y}? Answer with a "
                                f"number." + SUFFIX),
                        answer_type="number", grader={"kind": "numeric_tol", "abs": 0}, answer=n,
                        layers=["food_inspections", "code_inspections"], min_tool_calls=4,
                        intermediate={"food_rows": fr, "code_rows": cr}))
    return out


# ---- chain: 8+ dependent hops -------------------------------------------------------------------

def t_chain(con):
    out, seen = [], set()
    variants = [(400, "2024-01-01"), (300, "2023-01-01"), (500, "2025-01-01")]
    for i, r in enumerate(_resolvable_licences(con)):
        if r["city"] != "Minneapolis" or r["parcel_id"] in seen:
            continue
        radius, since = variants[len(out) % len(variants)]
        site = q(con, f"""select site, lat, lon, {near(r['lat'], r['lon'], 'c')} d from contamination c
                         where status='open' and kind like '%cleanup%' and lat is not null order by d, site limit 2""")
        if len(site) < 2 or site[1][3] - site[0][3] < 25 or site[0][3] > 1500:
            continue
        sname, slat, slon, _ = site[0]
        fac = q(con, f"""select facility_id, count(distinct violation_id) n from food_inspections f
                        where {near(slat, slon, 'f')} <= {radius} and violation_priority='Priority1'
                          and inspection_date between '2025-01-01' and '2025-12-31'
                        group by 1 order by n desc, 1 limit 2""")
        if len(fac) < 2 or fac[0][1] == fac[1][1]:
            continue
        fid = fac[0][0]
        pids = q(con, "select distinct parcel_id from food_inspections where facility_id=? and parcel_id is not null", [fid])
        if len(pids) != 1:
            continue
        n = q(con, "select count(distinct inspection_id) from code_inspections where parcel_id=? and completed >= ?",
              [pids[0][0], since])[0][0]
        if n < 3:
            continue
        seen.add(r["parcel_id"])
        out.append(dict(template="chain", tier=4, skills=["entity-resolution", "spatial", "nearest", "aggregate",
                                                          "dedup-trap", "multi-hop"],
            prompt=(f"Start from \"{r['business']}\" in the Minneapolis licence register and find the tax parcel it "
                    f"operates on. Find the open MPCA site of kind cleanup (kind contains 'cleanup') nearest to that "
                    f"parcel. Within {radius} metres of that site, find the food facility with the most Priority1 "
                    f"violations on inspections dated in 2025. On the tax parcel where that facility sits, how many "
                    f"code inspections were completed on or after {since}? Answer with a number." + SUFFIX),
            answer_type="number", grader={"kind": "numeric_tol", "abs": 0}, answer=n,
            layers=["licences", "parcels", "contamination", "food_inspections", "code_inspections"], min_tool_calls=8,
            intermediate={"register_address": r["address"], "parcel": r["parcel_id"], "site": sname,
                          "facility": fid, "facility_parcel": pids[0][0]}))
        if len(out) >= 40:
            break
    return out


R4_TEMPLATES = [t_fees_two_cities, t_sales_ratio_median, t_chain, t_ratio_parcels_assessed, t_food_code_overlap,
                t_permits_days, t_sold_above_assessed_count]

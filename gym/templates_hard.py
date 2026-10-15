"""Round-2 templates: the ones a frontier model with tools should fail some of the time.

Each one is built around a specific way the obvious approach is wrong, taken from
the layers' own read-before-quoting notes (gym/layer_notes.json):

  messy_address_parcel   the register's address (units, suites, 'AVE N' vs 'Avenue North',
                         'NE' vs 'N E') is not the parcel situs; geocode needs it normalised
  licence_coverage       the city registers stop at the city line, so a suburb with no rows
                         is NOT_OBSERVED, not zero ("absence is not evidence")
  permit_fees_month      Minneapolis publishes one row per parcel per permit and repeats the
                         fee on each, so summing rows over-counts; the month has more than
                         2,000 permits, so the answer needs paging past the cap plus calc
  city_permit_compare    rows vs distinct permits can flip the winner; Saint Paul's register
                         ends 2025-06-30, so a later window is NOT_COMPARABLE
  chain                  8+ dependent hops: register name -> messy address -> parcel ->
                         nearest open cleanup site -> worst food facility nearby ->
                         its parcel -> distinct code inspections

Every key is computed here by SQL. Nothing is typed.
"""
import re

import duckdb

KEYS_PARQUET = "answer_keys/licence_sites.parquet"
PER = 8


def q(con, sql, args=None):
    return con.execute(sql, args or []).fetchall()


def md5order(col, salt="prg-v2"):
    return f"md5(cast({col} as varchar) || '{salt}')"


def near(lat, lon, alias):
    return (f"2*6371008.8*asin(sqrt(pow(sin(radians({alias}.lat-({lat}))/2),2)"
            f"+cos(radians({lat}))*cos(radians({alias}.lat))*pow(sin(radians({alias}.lon-({lon}))/2),2)))")


# ---- address canonicalisation (key-side only: decides whether a register address
# ---- resolves to exactly one parcel situs; the agent has to do this itself) ------------
_WORDS = {"AVENUE": "AVE", "STREET": "ST", "BOULEVARD": "BLVD", "PARKWAY": "PKWY", "ROAD": "RD",
          "DRIVE": "DR", "PLACE": "PL", "LANE": "LN", "COURT": "CT", "TERRACE": "TER", "CIRCLE": "CIR",
          "HIGHWAY": "HWY", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE",
          "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW"}


def canon(a):
    a = (a or "").upper()
    a = re.sub(r",\s*(MINNEAPOLIS|SAINT PAUL|ST\.? PAUL).*$", "", a)
    a = re.sub(r"\s*(#|\bSTE\b\.?|\bSUITE\b|\bUNIT\b|\bAPT\b|\bFL\b|\bFLOOR\b|\bRM\b|\bROOM\b)\s*[\w-]*.*$", "", a)
    a = re.sub(r"[.,]", " ", a)
    toks = [_WORDS.get(t, t) for t in a.split()]
    s = " ".join(toks)
    s = re.sub(r"\b([NS]) ([EW])\b", r"\1\2", s)  # 'N E' -> 'NE'
    return s.strip()


def _situs_index(con):
    """canonical situs -> list of (parcel_id, county, address) per city, Minneapolis + Saint Paul."""
    idx = {}
    for pid, county, addr, city in q(con, "select parcel_id, county, address, city from parcels "
                                          "where city in ('Minneapolis','Saint Paul') and address is not null"):
        idx.setdefault((city, canon(addr)), []).append((pid, county, addr))
    return idx


def _resolvable_licences(con):
    """Register rows whose written address differs from the parcel situs but canonicalises to
    exactly one parcel in that city, and that parcel is the one the key table names."""
    idx = _situs_index(con)
    rows = q(con, f"""select k.business, k.type, k.address, k.city, k.site_parcel_id, k.county, p.address, p.lat, p.lon
                      from read_parquet('{KEYS_PARQUET}') k
                      join parcels p on p.parcel_id = k.site_parcel_id and p.county = k.county
                      where k.city in ('Minneapolis','Saint Paul')
                        and upper(k.address) != upper(p.address)
                        and (select count(*) from licences l where l.business = k.business) = 1
                      order by {md5order('k.business')}""")
    out = []
    for biz, typ, laddr, city, pid, county, paddr, lat, lon in rows:
        hits = idx.get((city, canon(laddr)), [])
        if len(hits) == 1 and hits[0][0] == pid and hits[0][1] == county and "ADDRESS" not in paddr.upper():
            out.append(dict(business=biz, type=typ, address=laddr, city=city, parcel_id=pid, county=county,
                            situs=paddr, lat=lat, lon=lon))
    return out


SUFFIX = " If the layers cannot answer a question, or one part of it, give NOT_OBSERVED for that part."
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def mname(m):
    return f"{MONTHS[int(m[5:7]) - 1]} {m[:4]}"


def t_messy_set(con):
    """Three register entries, one per kind of mess; all three must resolve."""
    pool = {"unit": [], "spelled": [], "spacing": []}  # five per question: 2 unit, 2 spelled-out, 1 spacing
    for r in _resolvable_licences(con):
        kind = ("unit" if re.search(r"#|STE|SUITE|UNIT", r["address"].upper()) else
                "spelled" if re.search(r"Avenue|Street|North|South|East|West", r["situs"]) else "spacing")
        pool[kind].append(r)
    out = []
    for i in range(PER):
        trio = [pool["unit"][2 * i], pool["spelled"][2 * i], pool["spacing"][i], pool["unit"][2 * i + 1],
                pool["spelled"][2 * i + 1]] if len(pool["unit"]) > 2 * i + 1 and len(pool["spelled"]) > 2 * i + 1 \
            and len(pool["spacing"]) > i else []
        if len({t["parcel_id"] for t in trio}) < 5:
            continue
        trio = trio[i % 5:] + trio[:i % 5]
        names = "; ".join(f'"{t["business"]}" ({t["city"]})' for t in trio)
        out.append(dict(template="messy_set", tier=4, skills=["entity-resolution", "multi-layer"],
            prompt=(f"These businesses appear in the city licence registers: {names}. On which tax parcels do they "
                    f"operate? Answer with the set of parcel IDs." + SUFFIX),
            answer_type="set", grader={"kind": "set_f1", "pass_at": 1.0}, answer=sorted(t["parcel_id"] for t in trio),
            layers=["licences", "parcels"], min_tool_calls=10,
            intermediate=[{"register_address": t["address"], "parcel_situs": t["situs"]} for t in trio]))
    return out


def t_licence_coverage(con):
    """Silent 'absence is not evidence': the city registers stop at the city line."""
    out = []
    types = ["liquor on sale", "liquor off sale"]  # the only types both city registers carry
    suburbs = [c for (c,) in q(con, f"""select city from parcels where city not in ('Minneapolis','Saint Paul')
                        and city not in (select distinct city from licences where city is not null)
                        group by 1 having count(*) > 8000 order by {md5order('city')}""")]
    for i in range(PER):
        typ = types[i % len(types)]
        cities = [suburbs[(2 * i) % len(suburbs)], "Minneapolis", suburbs[(2 * i + 1) % len(suburbs)], "Saint Paul"]
        cities = cities[i % 4:] + cities[:i % 4]
        ans = {c: (str(q(con, "select count(*) from licences where city=? and type=?", [c, typ])[0][0])
                   if c in ("Minneapolis", "Saint Paul") else "NOT_OBSERVED") for c in cities}
        out.append(dict(template="licence_coverage", tier=3, skills=["coverage", "abstention", "count"],
            prompt=(f"For each of these cities -- {', '.join(cities)} -- how many '{typ}' licences are on record? "
                    f"Answer as a JSON object mapping city to count." + SUFFIX),
            answer_type="map", grader={"kind": "map_f1", "pass_at": 1.0}, answer=ans, layers=["licences"],
            min_tool_calls=3))
    return out


def t_fees_two_cities(con):
    """Silent: Minneapolis repeats a permit's fee on every parcel row (sum distinct permits, >2,000
    of them, so page past the cap and add with calc); Saint Paul publishes no fee at all."""
    assert q(con, "select count(fees_usd) from permits where city='Saint Paul'")[0][0] == 0
    out = []
    for m, ds, n, rs in q(con, f"""with r as (select strftime(issued,'%Y-%m') m, sum(fees_usd) rs from permits
                                   where city='Minneapolis' group by 1),
                             d as (select m, sum(fees_usd) ds, count(*) n from (select distinct strftime(issued,'%Y-%m') m,
                                   permit_no, fees_usd from permits where city='Minneapolis') group by 1)
                        select m, ds, n, rs from r join d using(m)
                        where n > 2000 and rs > 1.15 * ds and m <= '2025-06'
                        order by {md5order('m')} limit {PER}"""):
        out.append(dict(template="fees_two_cities", tier=4,
            skills=["aggregate", "paging", "dedup-trap", "coverage", "arithmetic"],
            prompt=(f"What was the total of the permit fees charged on building permits issued in {mname(m)}, "
                    f"for Minneapolis and for Saint Paul separately? Answer as a JSON object mapping city to USD." + SUFFIX),
            answer_type="map", grader={"kind": "map_f1", "pass_at": 1.0},
            answer={"Minneapolis": str(int(ds)), "Saint Paul": "NOT_OBSERVED"}, layers=["permits"], min_tool_calls=4,
            intermediate={"distinct_permits": n, "naive_row_sum": int(rs)}))
    return out


def t_sales_ratio_median(con):
    """Paging past the 2,000-row cap: a median over 2,000-5,000 sales, computed with calc, where the
    filter has to exclude multi-parcel deeds (the price on those rows is the whole deal's)."""
    out = []
    for county in ("Hennepin", "Ramsey", "Anoka"):
        for start in ("2012-01", "2014-01", "2015-01", "2016-01", "2018-01", "2020-01"):
            n, med = q(con, """select count(*), median(price * 1.0 / assessed) from sales
                              where county = ? and arms_length and assessed > 0 and sale_month >= ?
                                and not coalesce(multi_parcel_deed, false)""", [county, start])[0]
            naive = q(con, """select median(price * 1.0 / assessed) from sales where county = ? and arms_length
                              and assessed > 0 and sale_month >= ?""", [county, start])[0][0]
            if 2000 < n <= 5000 and abs(naive - med) > 0.002:
                out.append(dict(template="sales_ratio_median", tier=4, skills=["aggregate", "paging", "arithmetic", "filter-trap"],
                    prompt=(f"Across all arms-length recorded sales in {county} County from {mname(start)} onward, "
                            f"counting only sales whose recorded price is for that one parcel alone (not a price "
                            f"shared across several parcels on one deed), what is the median ratio of sale price to "
                            f"assessed value? Leave out parcels with no assessed value. Answer with a number rounded "
                            f"to 3 decimals." + SUFFIX),
                    answer_type="number", grader={"kind": "numeric_tol", "abs": 0.0006}, answer=round(med, 4),
                    layers=["sales"], min_tool_calls=4,
                    intermediate={"sales": n, "median_if_multi_parcel_kept": round(naive, 4)}))
    return out


def t_permits_compare(con):
    """Silent: rows vs distinct permits flips the winner in some months; Saint Paul's register
    ends 2025-06-30, so a later window has no answer."""
    rows = q(con, """with x as (select strftime(issued,'%Y-%m') m, city, count(*) n, count(distinct permit_no) d
                                from permits group by all)
                     select a.m, a.n, a.d, b.n, b.d from x a join x b on a.m=b.m and a.city='Minneapolis' and b.city='Saint Paul'
                     order by a.m""")
    flips = [r for r in rows if (r[1] > r[3]) != (r[2] > r[4]) and r[2] != r[4]]
    plain = [r for r in rows if (r[1] > r[3]) == (r[2] > r[4]) and abs(r[2] - r[4]) > 300]
    covers = ["calendar year 2025", "the second half of 2025 (July through December)", "September 2025", "2026 so far"]
    out = []
    for i in range(min(PER, len(flips))):
        a, a2, b = flips[i], flips[(i + 4) % len(flips)], plain[(i * 7) % len(plain)]
        if a2 is a:
            continue
        wins = [(mname(r[0]), "Minneapolis" if r[2] > r[4] else "Saint Paul") for r in (a, b, a2)]
        wins.append((covers[i % len(covers)], "NOT_OBSERVED"))
        wins = wins[i % 4:] + wins[:i % 4]
        out.append(dict(template="permits_compare", tier=3, skills=["coverage", "dedup-trap", "comparison"],
            prompt=(f"For each of these periods -- {'; '.join(w for w, _ in wins)} -- which city issued more building "
                    f"permits, Minneapolis or Saint Paul? Answer as a JSON object mapping each period, exactly as "
                    f"written here, to the city." + SUFFIX),
            answer_type="map", grader={"kind": "map_f1", "pass_at": 1.0}, answer=dict(wins), layers=["permits"],
            min_tool_calls=8, intermediate={"flip_counts_mpls_rows_distinct_stp_rows_distinct": list(a[1:])}))
    return out


def t_sale_history(con):
    """Silent: the sales layer is the LAST sale of record per parcel, so an earlier sale of a
    parcel that has sold since is not in these layers at all."""
    cands = q(con, f"""select p.address, p.city, s.sale_month, s.price, p.last_sale_month, p.last_sale_price
                      from sales s join parcels p on p.parcel_id = s.parcel_id and p.county = s.county
                      where p.address is not null and s.price > 1000 and s.arms_length
                        and (select count(*) from parcels p2 where p2.address = p.address and p2.city = p.city) = 1
                      order by {md5order('s.parcel_id || s.county')} limit 400""")
    old = [c for c in cands if c[2] < "2019-01" and c[2] >= "2005-01" and c[4] == c[2] and c[5] == c[3]]
    new = [c for c in cands if c[2] >= "2020-01" and c[4] == c[2] and c[5] == c[3]]
    out = []
    for i in range(min(PER, len(new), len(old) // 2)):
        trio = [old[2 * i], new[i], old[2 * i + 1]]
        trio = trio[i % 3:] + trio[:i % 3]
        ans = {f"{a}, {c}": (str(price) if sm < "2019-01" else "NOT_OBSERVED") for a, c, sm, price, _, _ in trio}
        out.append(dict(template="sale_history", tier=3, skills=["coverage", "temporal", "abstention"],
            prompt=(f"For each of these properties -- {'; '.join(ans)} -- what was the price of its most recent "
                    f"recorded sale before January 2019? Answer as a JSON object mapping each address, exactly as "
                    f"written here, to the price in USD." + SUFFIX),
            answer_type="map", grader={"kind": "map_f1", "pass_at": 1.0}, answer=ans, layers=["parcels", "sales"],
            min_tool_calls=3, intermediate={"last_sales": [[a, sm, price] for a, _, sm, price, _, _ in trio]}))
    return out


def t_food_fail(con):
    """Silent: one row per violation (count distinct inspection ids), and the city publishes no pass/fail."""
    out = []
    for nb, y, n, r in q(con, f"""select * from (
                                select neighborhood nb, year(inspection_date) y, count(distinct inspection_id) n, count(*) r
                                from food_inspections where violation_priority='Priority1' and neighborhood is not null
                                  and year(inspection_date) in (2023, 2024, 2025)
                                group by 1, 2 having n between 15 and 160 and r > n * 1.3)
                                order by md5(nb || cast(y as varchar) || 'prg-v3') limit {PER}"""):
        out.append(dict(template="food_fail", tier=3, skills=["dedup-trap", "coverage", "count"],
            prompt=(f"In {y}, in the Minneapolis neighborhood {nb}, how many food inspections recorded at least one "
                    f"Priority1 violation, and how many food inspections failed? Answer as a JSON object with keys "
                    f"priority1_inspections and failed_inspections." + SUFFIX),
            answer_type="map", grader={"kind": "map_f1", "pass_at": 1.0},
            answer={"priority1_inspections": str(n), "failed_inspections": "NOT_OBSERVED"},
            layers=["food_inspections"], min_tool_calls=2, intermediate={"priority1_rows": r}))
    return out


def t_chain(con):
    out, seen = [], set()
    for r in _resolvable_licences(con):
        if r["city"] != "Minneapolis" or r["parcel_id"] in seen:
            continue
        site = q(con, f"""select site, lat, lon, {near(r['lat'], r['lon'], 'c')} d from contamination c
                         where status='open' and kind like '%cleanup%' and lat is not null order by d, site limit 2""")
        if len(site) < 2 or site[1][3] - site[0][3] < 25 or site[0][3] > 1500:
            continue
        sname, slat, slon, _ = site[0]
        # count VIOLATIONS, not rows: the city's feed repeats some violation rows (40,228 rows,
        # 37,901 distinct violation ids). Round 2's key counted rows; Sonnet counted ids and was right.
        fac = q(con, f"""select facility_id, count(distinct violation_id) n from food_inspections f
                        where {near(slat, slon, 'f')} <= 400 and violation_priority='Priority1'
                          and inspection_date between '2025-01-01' and '2025-12-31'
                        group by 1 order by n desc, 1 limit 2""")
        if len(fac) < 2 or fac[0][1] == fac[1][1]:
            continue
        fid = fac[0][0]
        pids = q(con, "select distinct parcel_id from food_inspections where facility_id=? and parcel_id is not null", [fid])
        if len(pids) != 1:
            continue
        n = q(con, "select count(distinct inspection_id) from code_inspections where parcel_id=? and completed >= '2024-01-01'",
              [pids[0][0]])[0][0]
        if n < 3:
            continue
        seen.add(r["parcel_id"])
        out.append(dict(template="chain", tier=4, skills=["entity-resolution", "spatial", "nearest", "aggregate",
                                                          "dedup-trap", "multi-hop"],
            prompt=(f"Start from \"{r['business']}\" in the Minneapolis licence register and find the tax parcel it "
                    f"operates on. Find the open MPCA site of kind cleanup (kind contains 'cleanup') nearest to that "
                    f"parcel. Within 400 metres of that site, find the food facility with the most Priority1 "
                    f"violations on inspections dated in 2025. On the tax parcel where that facility sits, how many "
                    f"code inspections were completed on or after 2024-01-01? Answer with a number." + SUFFIX),
            answer_type="number", grader={"kind": "numeric_tol", "abs": 0}, answer=n,
            layers=["licences", "parcels", "contamination", "food_inspections", "code_inspections"], min_tool_calls=8,
            intermediate={"register_address": r["address"], "parcel": r["parcel_id"], "site": sname,
                          "facility": fid, "facility_parcel": pids[0][0]}))
        if len(out) >= PER:
            break
    return out


HARD_TEMPLATES = [t_sales_ratio_median, t_messy_set, t_licence_coverage, t_fees_two_cities, t_permits_compare, t_sale_history,
                  t_food_fail, t_chain]

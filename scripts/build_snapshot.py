"""Freeze the Brick & Mortar substrate into one read-only DuckDB file.

Every answer key is only valid against this snapshot. Sources are the published
bricks export slices (each already has a LAYER_RIGHTS entry, basis
mn-public-data) plus the City of Minneapolis food-inspection cache.

Exclusions enforced here, not downstream:
  - no Google / Outscraper layers (review_corpus, reviews_example, occupants, serp)
  - no rental licences (owner/applicant emails + phones)
  - permit applicant, applicant_address, contractor and contractor_address dropped
    (Saint Paul's contractor field carries a contact person's name and phone,
    "STACY ... (651-...) MUSKA ELECTRIC"; found 2026-10-15 by the contact-field test)
  - sale owner/taxpayer names dropped unless owner_type == 'entity'
  - food inspector free-text comments dropped
  - Minnesota only (Wichita slices never read)
"""
import glob
import json
import os
import re
import sys

import duckdb

BRICKS = os.path.expanduser("~/Desktop/workspace/bricks")
EXP = f"{BRICKS}/website/api/_data/exports"
FOOD = f"{BRICKS}/data/cache/licences/mpls_food_violations"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "snapshot.duckdb")


def rows_of(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = __import__("gzip").decompress(raw)
    d = json.loads(raw)
    if isinstance(d, list):
        return d
    const = d.get("constants") or {}
    return [{**const, **r} for r in d["rows"]]


def load(con, table, rows, cols):
    tmp = OUT + f".{table}.jsonl"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps({c: r.get(c) for c in cols}) + "\n")
    con.execute(f"create table {table} as select * from read_json_auto('{tmp}', maximum_object_size=10000000, sample_size=-1)")
    os.remove(tmp)
    print(table, con.execute(f"select count(*) from {table}").fetchone()[0], file=sys.stderr)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    con = duckdb.connect(OUT)

    parcels = []
    for f in sorted(glob.glob(f"{EXP}/parcels/*-*.json")):
        county = os.path.basename(f).split("-")[0].title()
        for r in rows_of(f):
            r["county"] = county
            parcels.append(r)
    load(con, "parcels", parcels, ["parcel_id", "address", "city", "county", "use", "year_built",
                                   "assessed", "lot_sqft", "building_sqft", "stories",
                                   "last_sale_price", "last_sale_month", "lat", "lon"])

    sales = rows_of(f"{EXP}/sales.json")
    for r in sales:
        if r.get("owner_type") != "entity":
            r["owner"] = None
        r["county"] = (r.get("county") or "").replace(" County, Minnesota", "")
    load(con, "sales", sales, ["parcel_id", "address", "county", "sale_month", "price", "assessed",
                               "use", "year_built", "owner", "owner_type", "arms_length",
                               "multi_parcel_deed", "usable_comp"])

    permits = []
    for f in sorted(glob.glob(f"{EXP}/permits-residential/*-*.json")):
        permits += rows_of(f)
    load(con, "permits", permits, ["permit_no", "issued", "completed", "city", "kind", "work", "trade",
                                   "occupancy", "status", "value_usd", "fees_usd",
                                   "units_added", "units_removed", "rows_per_permit", "parcel_id", "lat", "lon"])

    insp = []
    for f in sorted(glob.glob(f"{EXP}/code-inspections/minneapolis-20*.json.gz")):
        insp += rows_of(f)
    load(con, "code_inspections", insp, ["inspection_id", "case_number", "case_type", "case_group",
                                         "inspection", "result", "scheduled", "completed",
                                         "address", "parcel_id", "lat", "lon"])

    food = []
    for f in sorted(glob.glob(f"{FOOD}/*.json")):
        for x in json.load(open(f))["features"]:
            a = x["attributes"]
            food.append({
                "facility_id": a["HealthFacilityIDNumber"], "business": a["BusinessName"],
                "category": a["FacilityCategory"], "risk_level": a["RiskLevel"],
                "address": a["FullAddress"], "inspection_id": a["InspectionIDNumber"],
                "inspection_type": a["InspectionType"],
                "inspection_date": None if a["DateOfInspection"] is None else
                    __import__("datetime").datetime.utcfromtimestamp(a["DateOfInspection"] / 1000).date().isoformat(),
                "score": a["InspectionScore"], "violation_id": a["ViolationIDNumber"],
                "violation_priority": a["ViolationPriority"], "violation_points": a["ViolationPoints"],
                "food_code_item": a["FoodCodeItem"], "parcel_id": a["APN"],
                "neighborhood": a["Neighborhood"], "lat": a["Latitude"], "lon": a["Longitude"],
            })
    load(con, "food_inspections", food, list(food[0].keys()))

    cont = rows_of(f"{EXP}/contamination.json")
    for r in cont:
        r["county"] = (r.get("county") or "").replace(" County, Minnesota", "")
    load(con, "contamination", cont,
         ["site", "address", "city", "county", "parcel_id", "status", "kind", "activity", "programs", "tanks",
          "cleanup", "institutional_controls", "industry"])

    # Some Saint Paul register rows carry a phone or email typed into the business
    # name ("Deb 612-...", "...@gmail.com"). Strip them: no contact field ships.
    lic = rows_of(f"{EXP}/licences.json")
    for r in lic:
        b = r.get("business") or ""
        b = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", "", b)
        b = re.sub(r"(?:\bc)?\(?\d{3}\)?[-. ]?\d{3}[-. ]\d{4}(\s*\(\d+/\d+\))?", "", b)
        r["business"] = re.sub(r"[\s\-]+$", "", re.sub(r"\s+", " ", b)).strip()
    for r in lic:
        r["county"] = (r.get("county") or "").replace(" County, Minnesota", "")
    load(con, "licences_full", lic,
         ["business", "type", "category", "address", "status", "expires", "licensed_since",
          "site_parcel_id", "joined_on", "county", "source"])

    # PARCEL IDS ARE UNIQUE WITHIN A COUNTY, NOT ACROSS THE MARKET (2,582 Carver/Scott
    # PINs collide). Every parcel join below carries the county. Round 1 deduped on the
    # PIN alone and silently dropped 2,582 parcels; fixed 2026-10-15.
    for t in ("sales", "contamination"):
        con.execute(f"""create or replace table {t} as
            select t.*, p.city as parcel_city, p.lat, p.lon
            from {t} t left join parcels p on p.parcel_id = t.parcel_id and p.county = t.county""")

    # The register as an agent sees it: name, type, address AS WRITTEN, the city the
    # register covers, status. The licensing office's own parcel id and our coordinate
    # are withheld from the agent -- resolving the register address to a parcel is the
    # task -- and kept as an answer-key table outside the snapshot.
    con.execute("""create or replace table licences_full as
        select l.*, coalesce(p.city, case when l.source ilike 'Minneapolis%' then 'Minneapolis'
                                          when l.source ilike 'Saint Paul%' then 'Saint Paul' end) as city,
               p.lat, p.lon
        from licences_full l left join parcels p on p.parcel_id = l.site_parcel_id and p.county = l.county""")
    con.execute("""create table licences as
        select business, type, category, address, city, status, expires, licensed_since, source
        from licences_full""")
    keys = os.path.join(os.path.dirname(__file__), "..", "answer_keys", "licence_sites.parquet")
    con.execute(f"copy (select row_number() over () as rid, * from licences_full) to '{os.path.abspath(keys)}' (format parquet)")
    con.execute("drop table licences_full")

    # The publisher-side caveats each layer ships with, served by the layer_notes tool.
    notes = {}
    for layer, f in [("parcels", "parcels.json"), ("sales", "sales.json"), ("permits", "permits-residential.json"),
                     ("code_inspections", "code-inspections.json"), ("contamination", "contamination.json"),
                     ("licences", "licences.json")]:
        notes[layer] = json.load(open(f"{EXP}/{f}")).get("read_before_quoting")
    notes["food_inspections"] = (
        "A ROW IS A VIOLATION, NOT AN INSPECTION: an inspection with five violations is five rows sharing an "
        "inspection_id, and an inspection with none is one row with violation_priority null. Count inspections with "
        "distinct inspection_id. THE CITY'S FEED ALSO REPEATS SOME VIOLATION ROWS: 40,228 violation rows carry "
        "37,901 distinct violation_id values, so count violations by distinct violation_id, not by rows. THE CITY PUBLISHES NO PASS/FAIL: every inspection's result is 'Complete'; "
        "violation_priority (Priority1 most serious) and score are the only severity signals. MINNEAPOLIS ONLY, "
        "inspections dated 2023 onward; 2026 is a partial year. facility_id is the city's health licence number.")
    notes["licences"] += (" GYM NOTE: the licence register is served here as the registers publish it -- name, type, "
                          "address as written (units, suites and abbreviations included) and the city whose register "
                          "it is. Resolve an address to a parcel with geocode.")
    json.dump(notes, open(os.path.join(os.path.dirname(__file__), "..", "gym", "layer_notes.json"), "w"), indent=1)

    con.execute("create table meta as select '2026-10-15' as snapshot, "
                "'Brick & Mortar export slices + Minneapolis food inspections' as source")
    pq = os.path.join(os.path.dirname(OUT), "snapshot")
    __import__("shutil").rmtree(pq, ignore_errors=True)
    con.execute(f"export database '{os.path.abspath(pq)}' (format parquet, compression zstd)")
    os.remove(os.path.join(pq, "load.sql"))  # absolute paths; gym/tools.py loads schema.sql + parquet instead
    con.close()


if __name__ == "__main__":
    main()

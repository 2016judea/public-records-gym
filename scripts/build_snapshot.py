"""Freeze the Brick & Mortar substrate into one read-only DuckDB file.

Every answer key is only valid against this snapshot. Sources are the published
bricks export slices (each already has a LAYER_RIGHTS entry, basis
mn-public-data) plus the City of Minneapolis food-inspection cache.

Exclusions enforced here, not downstream:
  - no Google / Outscraper layers (review_corpus, reviews_example, occupants, serp)
  - no rental licences (owner/applicant emails + phones)
  - permit applicant + applicant_address and contractor_address dropped
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

BRICKS = os.path.expanduser("~/Desktop/bricks")
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
    con.execute(f"create table {table} as select * from read_json_auto('{tmp}', maximum_object_size=10000000)")
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
                                   "occupancy", "status", "value_usd", "fees_usd", "contractor",
                                   "units_added", "units_removed", "parcel_id", "lat", "lon"])

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

    load(con, "contamination", rows_of(f"{EXP}/contamination.json"),
         ["site", "address", "city", "parcel_id", "status", "kind", "activity", "programs", "tanks",
          "cleanup", "institutional_controls", "industry"])

    # Some Saint Paul register rows carry a phone or email typed into the business
    # name ("Deb 612-...", "...@gmail.com"). Strip them: no contact field ships.
    lic = rows_of(f"{EXP}/licences.json")
    for r in lic:
        b = r.get("business") or ""
        b = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", "", b)
        b = re.sub(r"(?:\bc)?\(?\d{3}\)?[-. ]?\d{3}[-. ]\d{4}(\s*\(\d+/\d+\))?", "", b)
        r["business"] = re.sub(r"[\s\-]+$", "", re.sub(r"\s+", " ", b)).strip()
    load(con, "licences", lic,
         ["business", "type", "category", "address", "status", "expires", "licensed_since",
          "site_parcel_id", "source"])

    # One row per parcel (a handful of PINs repeat across shard edges), then give
    # every parcel-keyed layer the parcel's coordinate, as a county GIS layer would.
    con.execute("""create or replace table parcels as
        select * from parcels qualify row_number() over (
            partition by parcel_id order by assessed desc nulls last, address) = 1""")
    for t, key in [("sales", "parcel_id"), ("contamination", "parcel_id"), ("licences", "site_parcel_id")]:
        con.execute(f"""create or replace table {t} as
            select t.*, p.city as parcel_city, p.lat, p.lon
            from {t} t left join parcels p on p.parcel_id = t.{key}""")
    con.execute("create table meta as select '2026-10-15' as snapshot, "
                "'Brick & Mortar export slices + Minneapolis food inspections' as source")
    pq = os.path.join(os.path.dirname(OUT), "snapshot")
    __import__("shutil").rmtree(pq, ignore_errors=True)
    con.execute(f"export database '{os.path.abspath(pq)}' (format parquet, compression zstd)")
    os.remove(os.path.join(pq, "load.sql"))  # absolute paths; gym/tools.py loads schema.sql + parquet instead
    con.close()


if __name__ == "__main__":
    main()

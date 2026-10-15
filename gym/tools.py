"""The tool surface the agent gets. Deterministic, read-only, over the frozen snapshot.

Modelled on what a county ArcGIS REST layer offers: a `where` filter, chosen
fields, ordering, a row cap with paging, a count-only mode, and a point+radius
geometry filter. There is no GROUP BY: aggregation is the agent's job.
"""
import os
import re

import duckdb

DB = os.environ.get("GYM_DB", os.path.join(os.path.dirname(__file__), "..", "data", "snapshot.duckdb"))
ROW_CAP = 100
LAYERS = ["parcels", "sales", "permits", "code_inspections", "food_inspections", "contamination", "licences"]

LAYER_NOTES = {
    "parcels": "One row per tax parcel, 7 Twin Cities metro counties. assessed = total estimated market value (USD).",
    "sales": "The assessor's LAST recorded sale per commercial/apartment/industrial parcel (one row per parcel, can be decades old). sale_month 'YYYY-MM'. assessed = today's assessed value, not the value at sale. arms_length false = not a market sale; multi_parcel_deed true = the price is the whole deal's.",
    "permits": "Building permits, Minneapolis 2020-2026 and Saint Paul 2020-2025. issued is a DATE. value_usd is null for Minneapolis.",
    "code_inspections": "City of Minneapolis housing/nuisance/fire code inspections 2016-2026. One row per inspection.",
    "food_inspections": "City of Minneapolis food inspections 2023-2026. One row per VIOLATION (an inspection with no violation has one row with violation_priority null). inspection_date is 'YYYY-MM-DD'.",
    "contamination": "Minnesota Pollution Control Agency sites (cleanup, tanks). lat/lon are the parcel centroid.",
    "licences": "Business licences, Minneapolis + Saint Paul + state registers. lat/lon are the parcel centroid.",
}

_FORBIDDEN = re.compile(r";|--|/\*|\b(select|from|attach|copy|pragma|install|load|read_\w+|create|drop|insert|update|delete|alter|export|import|call)\b", re.I)
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


PARQUET = os.path.join(os.path.dirname(__file__), "..", "data", "snapshot")


def _con():
    if not os.path.exists(DB) and os.path.isdir(PARQUET):
        # the repo ships the snapshot as zstd parquet (git-sized); materialise it once
        # (not IMPORT DATABASE: its load.sql carries the exporting machine's absolute paths)
        with duckdb.connect(DB) as c:
            c.execute(open(os.path.join(PARQUET, "schema.sql")).read())
            for f in sorted(os.listdir(PARQUET)):
                if f.endswith(".parquet"):
                    c.execute(f"insert into {f[:-8]} select * from read_parquet('{os.path.abspath(os.path.join(PARQUET, f))}')")
    return duckdb.connect(DB, read_only=True)


def _hav(lat, lon):
    # metres, haversine, R = 6371008.8 (IUGG mean). The answer keys use this same expression.
    return (f"2*6371008.8*asin(sqrt(pow(sin(radians(lat-({lat}))/2),2)"
            f"+cos(radians({lat}))*cos(radians(lat))*pow(sin(radians(lon-({lon}))/2),2)))")


HAVERSINE_SQL = _hav


def _check(layer, where, fields, order_by):
    if layer not in LAYERS:
        raise ValueError(f"unknown layer {layer!r}; call list_layers")
    for part in (where or "", order_by or ""):
        if _FORBIDDEN.search(part):
            raise ValueError("where/order_by must be a filter expression, not a statement")
    cols = _columns(layer)
    for f in fields or []:
        if not _IDENT.match(f) or f not in cols:
            raise ValueError(f"unknown field {f!r} on {layer}; fields are {cols}")


_COLS = {}


def _columns(layer):
    if layer not in _COLS:
        with _con() as c:
            _COLS[layer] = [r[0] for r in c.execute(f"describe {layer}").fetchall()]
    return _COLS[layer]


def _rows(cur):
    names = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        out.append({n: (v.isoformat() if hasattr(v, "isoformat") else v) for n, v in zip(names, r)})
    return out


def list_layers():
    with _con() as c:
        return [{"layer": l, "rows": c.execute(f"select count(*) from {l}").fetchone()[0],
                 "fields": _columns(l), "notes": LAYER_NOTES[l]} for l in LAYERS]


def query_layer(layer, where="true", fields=None, order_by=None, limit=ROW_CAP, offset=0, count_only=False):
    _check(layer, where, fields, order_by)
    where = where or "true"
    with _con() as c:
        total = c.execute(f"select count(*) from {layer} where {where}").fetchone()[0]
        if count_only:
            return {"total": total}
        sel = ", ".join(fields) if fields else "*"
        order = f" order by {order_by}" if order_by else ""
        limit = max(1, min(int(limit), ROW_CAP))
        cur = c.execute(f"select {sel} from {layer} where {where}{order} limit {limit} offset {int(offset)}")
        return {"total": total, "offset": int(offset), "returned_rows": _rows(cur),
                "more": int(offset) + limit < total}


def query_near(layer, lat, lon, radius_m, where="true", fields=None, limit=ROW_CAP, offset=0, count_only=False):
    _check(layer, where, fields, None)
    lat, lon, radius_m = float(lat), float(lon), float(radius_m)
    if radius_m > 5000:
        raise ValueError("radius_m is capped at 5000")
    d = _hav(lat, lon)
    base = f"from {layer} where lat is not null and ({where or 'true'}) and {d} <= {radius_m}"
    with _con() as c:
        total = c.execute(f"select count(*) {base}").fetchone()[0]
        if count_only:
            return {"total": total}
        sel = ", ".join(fields) if fields else "*"
        limit = max(1, min(int(limit), ROW_CAP))
        cur = c.execute(f"select {sel}, round({d}, 1) as distance_m {base} order by {d}, 1 limit {limit} offset {int(offset)}")
        return {"total": total, "offset": int(offset), "returned_rows": _rows(cur),
                "more": int(offset) + limit < total}


def geocode(address, city=None):
    """Resolve a street address to parcel(s) and a coordinate."""
    a = re.sub(r"\s+", " ", address.strip().upper())
    with _con() as c:
        q = "select parcel_id, address, city, county, lat, lon from parcels where upper(address) = ?"
        args = [a]
        if city:
            q += " and lower(city) = lower(?)"
            args.append(city)
        cur = c.execute(q + " order by parcel_id limit 10", args)
        rows = _rows(cur)
        if not rows:
            cur = c.execute("select parcel_id, address, city, county, lat, lon from parcels where upper(address) like ? "
                            + ("and lower(city) = lower(?) " if city else "") + "order by parcel_id limit 10",
                            [a + "%"] + ([city] if city else []))
            rows = _rows(cur)
        return {"matches": rows}


def parcel_lookup(parcel_id):
    with _con() as c:
        p = _rows(c.execute("select * from parcels where parcel_id = ?", [parcel_id]))
        s = _rows(c.execute("select sale_month, price, assessed, arms_length, owner, owner_type from sales "
                            "where parcel_id = ? order by sale_month", [parcel_id]))
        return {"parcel": p[0] if p else None, "sales": s}


TOOLS = {
    "list_layers": list_layers,
    "query_layer": query_layer,
    "query_near": query_near,
    "geocode": geocode,
    "parcel_lookup": parcel_lookup,
}

SCHEMAS = [
    {"name": "list_layers", "description": "List the data layers, their fields, row counts and notes.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "query_layer",
     "description": "ArcGIS-style query on one layer. `where` is a SQL boolean expression over the layer's fields "
                    "(e.g. \"city = 'Saint Paul' and issued >= DATE '2024-01-01'\"). Returns at most 100 rows per call; "
                    "page with offset. count_only returns just the total. No GROUP BY.",
     "input_schema": {"type": "object", "properties": {
         "layer": {"type": "string"}, "where": {"type": "string"},
         "fields": {"type": "array", "items": {"type": "string"}}, "order_by": {"type": "string"},
         "limit": {"type": "integer"}, "offset": {"type": "integer"}, "count_only": {"type": "boolean"}},
         "required": ["layer"]}},
    {"name": "query_near",
     "description": "Rows of a layer whose lat/lon lie within radius_m metres (haversine) of a point, nearest first, "
                    "with distance_m. Optional `where` filter. 100 rows per call; page with offset.",
     "input_schema": {"type": "object", "properties": {
         "layer": {"type": "string"}, "lat": {"type": "number"}, "lon": {"type": "number"},
         "radius_m": {"type": "number"}, "where": {"type": "string"},
         "fields": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"},
         "offset": {"type": "integer"}, "count_only": {"type": "boolean"}},
         "required": ["layer", "lat", "lon", "radius_m"]}},
    {"name": "geocode", "description": "Resolve a street address (and optional city) to parcel id(s) and lat/lon.",
     "input_schema": {"type": "object", "properties": {"address": {"type": "string"}, "city": {"type": "string"}},
                      "required": ["address"]}},
    {"name": "parcel_lookup", "description": "One parcel's record plus its recorded sales.",
     "input_schema": {"type": "object", "properties": {"parcel_id": {"type": "string"}}, "required": ["parcel_id"]}},
]


def call(name, args):
    try:
        return TOOLS[name](**(args or {}))
    except Exception as e:  # the agent sees errors as tool output, as it would from a real API
        return {"error": f"{type(e).__name__}: {e}"}

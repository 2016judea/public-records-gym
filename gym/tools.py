"""The tool surface the agent gets. Deterministic, read-only, over the frozen snapshot.

Modelled on a county ArcGIS REST layer: a `where` filter, chosen fields, ordering,
a 2,000-row cap per call (ArcGIS's default maxRecordCount) with paging, count-only
and distinct-values modes, and a point+radius geometry filter. There is no GROUP BY
and no SUM: aggregation is the agent's job, with `calc` for arithmetic.
"""
import ast
import json
import math
import os
import re
import statistics

import duckdb

DB = os.environ.get("GYM_DB", os.path.join(os.path.dirname(__file__), "..", "data", "snapshot.duckdb"))
PARQUET = os.path.join(os.path.dirname(__file__), "..", "data", "snapshot")
ROW_CAP = 2000
LAYERS = ["parcels", "sales", "permits", "code_inspections", "food_inspections", "contamination", "licences"]
NOTES = json.load(open(os.path.join(os.path.dirname(__file__), "layer_notes.json")))

LAYER_SUMMARY = {
    "parcels": "One row per tax parcel, 7 Twin Cities metro counties. assessed = county assessed value (USD).",
    "sales": "The assessor's last recorded sale per commercial/apartment/industrial parcel. sale_month 'YYYY-MM'.",
    "permits": "Building permits, Minneapolis and Saint Paul. issued is a DATE.",
    "code_inspections": "City of Minneapolis housing/nuisance/fire code inspections.",
    "food_inspections": "City of Minneapolis food inspections. inspection_date 'YYYY-MM-DD'.",
    "contamination": "Minnesota Pollution Control Agency site files. lat/lon are the parcel centroid.",
    "licences": "City and state business licence registers, address as written. No coordinates.",
}

_FORBIDDEN = re.compile(r";|--|/\*|\b(select|from|attach|copy|pragma|install|load|read_\w+|create|drop|insert|"
                        r"update|delete|alter|export|import|call|query|glob)\b", re.I)
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


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


def haversine_sql(lat, lon, alias=None):
    """Metres from a fixed point to <alias.>lat/lon. The answer keys use this same expression."""
    a = f"{alias}." if alias else ""
    return (f"2*6371008.8*asin(sqrt(pow(sin(radians({a}lat-({lat}))/2),2)"
            f"+cos(radians({lat}))*cos(radians({a}lat))*pow(sin(radians({a}lon-({lon}))/2),2)))")


_COLS = {}


def _columns(layer):
    if layer not in _COLS:
        with _con() as c:
            _COLS[layer] = [r[0] for r in c.execute(f"describe {layer}").fetchall()]
    return _COLS[layer]


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


def _val(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _page(c, sel_sql, base_sql, order_sql, limit, offset, count_only, distinct, fields):
    if distinct and not fields:
        raise ValueError("distinct needs fields")
    inner = f"select distinct {sel_sql} {base_sql}" if distinct else f"select {sel_sql} {base_sql}"
    total = c.execute(f"select count(*) from ({inner})").fetchone()[0]
    if count_only:
        return {"total": total}
    limit = max(1, min(int(limit), ROW_CAP))
    order = order_sql or ("order by all" if distinct else "")
    cur = c.execute(f"{inner} {order} limit {limit} offset {int(offset)}")
    names = [d[0] for d in cur.description]
    rows = [[_val(v) for v in r] for r in cur.fetchall()]
    return {"total": total, "offset": int(offset), "fields": names, "rows": rows,
            "more": int(offset) + len(rows) < total}


def list_layers():
    with _con() as c:
        return [{"layer": l, "rows": c.execute(f"select count(*) from {l}").fetchone()[0],
                 "fields": _columns(l), "summary": LAYER_SUMMARY[l],
                 "caveats": "call layer_notes before relying on this layer"} for l in LAYERS]


def layer_notes(layer):
    if layer not in LAYERS:
        raise ValueError(f"unknown layer {layer!r}")
    return {"layer": layer, "read_before_quoting": NOTES[layer]}


def query_layer(layer, where="true", fields=None, order_by=None, limit=ROW_CAP, offset=0,
                count_only=False, distinct=False):
    _check(layer, where, fields, order_by)
    sel = ", ".join(fields) if fields else "*"
    with _con() as c:
        return _page(c, sel, f"from {layer} where {where or 'true'}", f"order by {order_by}" if order_by else "",
                     limit, offset, count_only, distinct, fields)


def query_near(layer, lat, lon, radius_m, where="true", fields=None, limit=ROW_CAP, offset=0,
               count_only=False, distinct=False):
    _check(layer, where, fields, None)
    if "lat" not in _columns(layer):
        raise ValueError(f"{layer} has no coordinates; resolve addresses with geocode")
    lat, lon, radius_m = float(lat), float(lon), float(radius_m)
    if radius_m > 5000:
        raise ValueError("radius_m is capped at 5000")
    d = haversine_sql(lat, lon)
    base = f"from {layer} where lat is not null and ({where or 'true'}) and {d} <= {radius_m}"
    with _con() as c:
        if distinct:
            return _page(c, ", ".join(fields), base, "", limit, offset, count_only, True, fields)
        sel = (", ".join(fields) if fields else "*") + f", round({d}, 1) as distance_m"
        return _page(c, sel, base, f"order by {d}, 1", limit, offset, count_only, False, fields)


def geocode(address, city=None):
    """Exact situs match first, then prefix. The parcel file's own address strings."""
    a = re.sub(r"\s+", " ", address.strip().upper())
    sel = "select parcel_id, county, address, city, lat, lon from parcels where "
    tail = (" and lower(city) = lower(?)" if city else "") + " order by county, parcel_id limit 10"
    with _con() as c:
        for op, arg in (("=", a), ("like", a + "%")):
            cur = c.execute(sel + f"upper(address) {op} ?" + tail, [arg] + ([city] if city else []))
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, map(_val, r))) for r in cur.fetchall()]
            if rows:
                return {"matches": rows}
        return {"matches": []}


def parcel_lookup(parcel_id, county=None):
    """Every parcel with this id (ids are unique only within a county), plus each one's recorded sale."""
    with _con() as c:
        q = "select * from parcels where parcel_id = ?" + (" and county = ?" if county else "")
        cur = c.execute(q, [parcel_id] + ([county] if county else []))
        names = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            p = dict(zip(names, map(_val, r)))
            s = c.execute("select sale_month, price, assessed, arms_length, multi_parcel_deed from sales "
                          "where parcel_id = ? and county = ?", [parcel_id, p["county"]]).fetchall()
            p["sales"] = [dict(zip(["sale_month", "price", "assessed", "arms_length", "multi_parcel_deed"], x)) for x in s]
            out.append(p)
        return {"parcels": out}


# ---- calc: arithmetic over numbers and lists, nothing else -------------------------------
_FUNCS = {"sum": sum, "len": len, "min": min, "max": max, "abs": abs, "round": round, "sorted": sorted,
          "median": statistics.median, "mean": statistics.mean, "sqrt": math.sqrt, "set": set}
_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.List, ast.Tuple, ast.Call, ast.Name,
          ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd,
          ast.Compare, ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq, ast.Subscript, ast.Slice)


def calc(expression):
    """Evaluate arithmetic: + - * / ** over numbers and lists, with sum len min max median mean round sorted set."""
    if len(expression) > 200_000:
        raise ValueError("expression too long")
    tree = ast.parse(expression, mode="eval")
    for n in ast.walk(tree):
        if not isinstance(n, _NODES) or (isinstance(n, ast.Name) and n.id not in _FUNCS) or \
                (isinstance(n, ast.Constant) and not isinstance(n.value, (int, float))):
            raise ValueError(f"not allowed in calc: {type(n).__name__}")
    v = eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, dict(_FUNCS))
    return {"result": sorted(v) if isinstance(v, set) else v}


TOOLS = {"list_layers": list_layers, "layer_notes": layer_notes, "query_layer": query_layer,
         "query_near": query_near, "geocode": geocode, "parcel_lookup": parcel_lookup, "calc": calc}


def call(name, args):
    try:
        return TOOLS[name](**(args or {}))
    except Exception as e:  # the agent sees errors as tool output, as it would from a real API
        return {"error": f"{type(e).__name__}: {e}"}

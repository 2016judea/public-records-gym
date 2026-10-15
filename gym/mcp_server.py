"""The harness as an MCP stdio server, so any MCP-speaking agent (Claude Code,
an Agent SDK loop, a lab's own runner) can call the same seven tools.

Every call is appended to $GYM_TRACE (jsonl) when set, which is the episode log.
"""
import json
import os
import time

from mcp.server.fastmcp import FastMCP

from gym import tools

mcp = FastMCP("public-records-gym")
TRACE = os.environ.get("GYM_TRACE")


def _run(name, args):
    out = tools.call(name, args)
    if TRACE:
        with open(TRACE, "a") as f:
            f.write(json.dumps({"t": time.time(), "tool": name, "args": args,
                                "error": out.get("error") if isinstance(out, dict) else None}) + "\n")
    return json.dumps(out, default=str, separators=(",", ":"))


@mcp.tool()
def list_layers() -> str:
    """List the data layers, their fields and row counts."""
    return _run("list_layers", {})


@mcp.tool()
def layer_notes(layer: str) -> str:
    """The publisher's read-before-quoting caveats for a layer: coverage, what a row is, known traps."""
    return _run("layer_notes", {"layer": layer})


@mcp.tool()
def query_layer(layer: str, where: str = "true", fields: list[str] | None = None, order_by: str | None = None,
                limit: int = 2000, offset: int = 0, count_only: bool = False, distinct: bool = False) -> str:
    """ArcGIS-style query on one layer. `where` is a SQL boolean expression over the layer's fields
    (e.g. "city = 'Saint Paul' and issued >= DATE '2024-01-01'"). At most 2,000 rows per call; page
    with offset while `more` is true. count_only returns the total. distinct returns distinct
    combinations of `fields` (with count_only: how many). No GROUP BY or SUM: use calc."""
    return _run("query_layer", dict(layer=layer, where=where, fields=fields, order_by=order_by, limit=limit,
                                    offset=offset, count_only=count_only, distinct=distinct))


@mcp.tool()
def query_near(layer: str, lat: float, lon: float, radius_m: float, where: str = "true",
               fields: list[str] | None = None, limit: int = 2000, offset: int = 0, count_only: bool = False,
               distinct: bool = False) -> str:
    """Rows of a layer whose lat/lon are within radius_m metres (haversine) of a point, nearest first,
    with distance_m. Optional `where`. 2,000 rows per call; page with offset. distinct as query_layer."""
    return _run("query_near", dict(layer=layer, lat=lat, lon=lon, radius_m=radius_m, where=where, fields=fields,
                                   limit=limit, offset=offset, count_only=count_only, distinct=distinct))


@mcp.tool()
def geocode(address: str, city: str | None = None) -> str:
    """Resolve a street address to parcel(s) using the parcel file's own situs strings: exact match,
    then prefix match. Unit numbers and spelled-out words will not match; normalise first."""
    return _run("geocode", dict(address=address, city=city))


@mcp.tool()
def parcel_lookup(parcel_id: str, county: str | None = None) -> str:
    """Every parcel carrying this id, with its recorded sale. Ids are unique only within a county."""
    return _run("parcel_lookup", dict(parcel_id=parcel_id, county=county))


@mcp.tool()
def calc(expression: str) -> str:
    """Arithmetic over numbers and lists: + - * / ** and sum len min max median mean round sorted set;
    elementwise div(a, b) mul add sub over two equal-length lists; intersect(a, b) union minus distinct
    over lists of ids. Examples: sum([120, 85, 85]); median(div([500, 900], [450, 1000]));
    len(intersect(["a", "b"], ["b", "c"]))."""
    return _run("calc", dict(expression=expression))


if __name__ == "__main__":
    mcp.run()

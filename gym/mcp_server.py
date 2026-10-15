"""The harness as an MCP stdio server, so any MCP-speaking agent (Claude Code,
an Agent SDK loop, a lab's own runner) can call the same five tools.

Every call is appended to $GYM_TRACE (jsonl) when set, which is the episode log.
"""
import json
import os
import time

from mcp.server.fastmcp import FastMCP

from gym import tools

mcp = FastMCP("public-records-gym")
TRACE = os.environ.get("GYM_TRACE")


def _log(name, args, out):
    if TRACE:
        with open(TRACE, "a") as f:
            f.write(json.dumps({"t": time.time(), "tool": name, "args": args,
                                "error": out.get("error") if isinstance(out, dict) else None}) + "\n")
    return json.dumps(out, default=str)


@mcp.tool()
def list_layers() -> str:
    """List the data layers, their fields, row counts and notes."""
    return _log("list_layers", {}, tools.call("list_layers", {}))


@mcp.tool()
def query_layer(layer: str, where: str = "true", fields: list[str] | None = None, order_by: str | None = None,
                limit: int = 100, offset: int = 0, count_only: bool = False) -> str:
    """ArcGIS-style query on one layer. `where` is a SQL boolean expression over the layer's fields
    (e.g. "city = 'Saint Paul' and issued >= DATE '2024-01-01'"). At most 100 rows per call; page with
    offset. count_only returns just the total. No GROUP BY: aggregate the rows yourself."""
    a = dict(layer=layer, where=where, fields=fields, order_by=order_by, limit=limit, offset=offset, count_only=count_only)
    return _log("query_layer", a, tools.call("query_layer", a))


@mcp.tool()
def query_near(layer: str, lat: float, lon: float, radius_m: float, where: str = "true",
               fields: list[str] | None = None, limit: int = 100, offset: int = 0, count_only: bool = False) -> str:
    """Rows of a layer whose lat/lon are within radius_m metres (haversine) of a point, nearest first,
    with distance_m. Optional `where` filter. At most 100 rows per call; page with offset."""
    a = dict(layer=layer, lat=lat, lon=lon, radius_m=radius_m, where=where, fields=fields, limit=limit,
             offset=offset, count_only=count_only)
    return _log("query_near", a, tools.call("query_near", a))


@mcp.tool()
def geocode(address: str, city: str | None = None) -> str:
    """Resolve a street address (and optional city) to parcel id(s) and lat/lon."""
    a = dict(address=address, city=city)
    return _log("geocode", a, tools.call("geocode", a))


@mcp.tool()
def parcel_lookup(parcel_id: str) -> str:
    """One parcel's record plus its recorded sales."""
    a = dict(parcel_id=parcel_id)
    return _log("parcel_lookup", a, tools.call("parcel_lookup", a))


if __name__ == "__main__":
    mcp.run()

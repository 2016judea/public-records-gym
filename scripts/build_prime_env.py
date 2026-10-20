"""Generate the Prime Intellect Environments Hub package (verifiers v1) from this repo.

Two builds, both GENERATED (never hand-edit prime/<name>/; edit gym/ and re-run this):

  full   prime/public_records_gym/        the train split (keys included, so the env can grade),
                                           the full 1.97M-row snapshot. Pushed PRIVATE.
  demo   prime/public_records_gym_demo/   the two tasks already public in
                                           github.com/2016judea/public-records-gym-sample, over only
                                           the permit rows those two questions read. Pushed PUBLIC.

The held-out test split and its keys are never copied into either build.

    uv run python -m scripts.build_prime_env            # both
    cd prime/public_records_gym && prime env push --visibility=PRIVATE
    cd prime/public_records_gym_demo && prime env push
"""
import json
import os
import shutil
import sys

import duckdb

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "prime")
DEMO_IDS = ["prg-cbeb9c48f9", "prg-4573caffa7"]  # the public sample repo's two tasks
LAYERS = ["parcels", "sales", "permits", "code_inspections", "food_inspections", "contamination", "licences"]

TOOLSET = '''import json
import os

import verifiers.v1 as vf

os.environ.setdefault("GYM_DB", os.path.join(os.path.expanduser("~"), ".cache", "{pkg}", "snapshot.duckdb"))
os.makedirs(os.path.dirname(os.environ["GYM_DB"]), exist_ok=True)

from {pkg}.core import tools  # noqa: E402


def _run(name, **args):
    return json.dumps(tools.call(name, {{k: v for k, v in args.items() if v is not None}}), default=str)


class PublicRecordsToolset(vf.Toolset[vf.ToolsetConfig]):
    """Seven read-only tools over a frozen snapshot of Minnesota public records, modelled on a county
    ArcGIS REST layer: a 2,000-row cap per call with paging, no GROUP BY, no SUM."""

    TOOL_PREFIX = "records"

    @vf.tool
    def list_layers(self) -> str:
        """List the layers, their row counts and fields."""
        return _run("list_layers")

    @vf.tool
    def layer_notes(self, layer: str) -> str:
        """The publisher's read-before-quoting caveats for one layer."""
        return _run("layer_notes", layer=layer)

    @vf.tool
    def query_layer(self, layer: str, where: str = "true", fields: list[str] | None = None,
                    order_by: str | None = None, limit: int = 2000, offset: int = 0,
                    count_only: bool = False, distinct: bool = False) -> str:
        """Filter one layer with an SQL-style where clause. At most 2,000 rows per call: page with offset
        while `more` is true. count_only returns the total; distinct returns distinct values of fields."""
        return _run("query_layer", layer=layer, where=where, fields=fields, order_by=order_by, limit=limit,
                    offset=offset, count_only=count_only, distinct=distinct)

    @vf.tool
    def query_near(self, layer: str, lat: float, lon: float, radius_m: float, where: str = "true",
                   fields: list[str] | None = None, limit: int = 2000, offset: int = 0,
                   count_only: bool = False, distinct: bool = False) -> str:
        """Rows of a layer within radius_m metres (max 5,000) of a point, nearest first."""
        return _run("query_near", layer=layer, lat=lat, lon=lon, radius_m=radius_m, where=where, fields=fields,
                    limit=limit, offset=offset, count_only=count_only, distinct=distinct)

    @vf.tool
    def geocode(self, address: str, city: str | None = None) -> str:
        """Match an address against the parcel file's own situs strings (exact, then prefix)."""
        return _run("geocode", address=address, city=city)

    @vf.tool
    def parcel_lookup(self, parcel_id: str, county: str | None = None) -> str:
        """Every parcel with this id (ids are unique only within a county), with its recorded sale."""
        return _run("parcel_lookup", parcel_id=parcel_id, county=county)

    @vf.tool
    def calc(self, expression: str) -> str:
        """Arithmetic over numbers and lists: + - * / **, sum len min max median mean round sorted set,
        elementwise div/mul/add/sub(list, list), intersect/union/minus/distinct over id lists."""
        return _run("calc", expression=expression)


if __name__ == "__main__":
    PublicRecordsToolset.run()
'''

TASKSET = '''import json
import os

import verifiers.v1 as vf

from {pkg}.core import grader
from {pkg}.servers.tool import PublicRecordsToolset

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM = ("You have tools over a frozen snapshot of Minnesota public records. Use the tools to compute the "
          "answer; do not guess. Read list_layers first if you need field names, and layer_notes before you "
          "trust a layer. When done, end your reply with one line: FINAL: <answer> (a number, an ID, a JSON "
          "list of IDs, or a JSON object, as the question asks).")


def final_answer(text):
    """Everything after the last FINAL:; no FINAL: grades the whole reply."""
    if not text:
        return None
    return text.rsplit("FINAL:", 1)[1].strip().strip("`*").strip() if "FINAL:" in text else text.strip()


class RecordsData(vf.TaskData):
    answer: str
    """The key, JSON-encoded. Computed by SQL over the snapshot, then re-derived through these tools."""
    grader: str
    """The grader spec, JSON-encoded: exact, set_f1, map_f1 or numeric_tol."""
    template: str
    tier: int


class RecordsTaskConfig(vf.TaskConfig):
    tools: vf.ToolsetConfig = vf.ToolsetConfig()


class RecordsTask(vf.Task[RecordsData, vf.State, RecordsTaskConfig]):
    @classmethod
    def toolsets(cls, config: RecordsTaskConfig) -> list[vf.Toolset]:
        return [PublicRecordsToolset(config.tools)]

    @vf.reward(weight=1.0)
    async def correct(self, trace: vf.Trace) -> float:
        g = grader.grade(json.loads(self.data.grader), json.loads(self.data.answer), final_answer(trace.last_reply))
        return float(g["reward"])


class RecordsConfig(vf.TasksetConfig):
    task: RecordsTaskConfig = RecordsTaskConfig()


class {cls}(vf.Taskset[RecordsTask, RecordsConfig]):
    def load(self) -> list[RecordsTask]:
        keys = {{k["task_id"]: k for k in map(json.loads, open(os.path.join(HERE, "data", "keys.jsonl")))}}
        out = []
        for t in map(json.loads, open(os.path.join(HERE, "data", "tasks.jsonl"))):
            k = keys[t["id"]]
            out.append(RecordsTask(RecordsData(id=t["id"], name=t["id"], prompt=t["prompt"], system_prompt=SYSTEM,
                                               answer=json.dumps(k["answer"]), grader=json.dumps(t["grader"]),
                                               template=k["template"], tier=t["tier"]), self.config.task))
        return out
'''


def readme(name, n, demo):
    head = (f"# {name}\n\n"
            "A tool-use RL environment over joined Minnesota public records, by Brick and Mortar AI LLC "
            "(brickandmortar.dev). An agent answers questions about land, buildings and businesses by "
            "querying seven public-record layers through an ArcGIS-style API (2,000 rows per call, no "
            "GROUP BY, no SUM). Every answer is computed from a frozen snapshot by SQL, re-derived through "
            "the agent's own tools, and graded without a model.\n\n"
            "The tasks are built around the ways the obvious query is wrong, and the traps are true in the "
            "rows and written in no layer note: a fee repeated on every parcel row of one permit, two "
            "assessed-value columns that disagree on 333 sales, county-scoped parcel ids that collide "
            "across Carver and Scott, permits completed before they were issued.\n\n")
    if demo:
        body = (f"**This is the public demo: {n} tasks over only the permit rows they read.** The full "
                "environment (227 tasks across 7 templates and 7 layers, 1.97M rows, a held-out test split "
                "with a measured frontier baseline) is licensed commercially: aidan@brickandmortar.dev.\n\n")
    else:
        body = (f"Train split: {n} tasks. The held-out test split and its keys are not in this package.\n\n"
                "Licence: commercial, by agreement with Brick and Mortar AI LLC (aidan@brickandmortar.dev).\n\n")
    return head + body + ("```bash\nprime env install <owner>/" + name + "\nuv run vf-eval " + name + " -n 2\n```\n")


def build(name, ids, demo):
    pkg = name.replace("-", "_")
    dst = os.path.join(OUT, pkg)
    shutil.rmtree(dst, ignore_errors=True)
    p = os.path.join(dst, pkg)
    os.makedirs(os.path.join(p, "core"))
    os.makedirs(os.path.join(p, "servers"))
    os.makedirs(os.path.join(p, "data", "snapshot"))
    for f in ("tools.py", "grader.py", "layer_notes.json"):
        shutil.copy(os.path.join(ROOT, "gym", f), os.path.join(p, "core", f))
    open(os.path.join(p, "core", "__init__.py"), "w").close()
    open(os.path.join(p, "servers", "__init__.py"), "w").close()
    open(os.path.join(p, "servers", "tool.py"), "w").write(TOOLSET.format(pkg=pkg))
    cls = "".join(w.title() for w in pkg.split("_")) + "Taskset"
    open(os.path.join(p, "taskset.py"), "w").write(TASKSET.format(pkg=pkg, cls=cls))
    # the default harness is a plain tool-calling chat loop (verifiers' null harness): no shell, so the
    # agent reaches the records only through the seven tools, never the package's files
    open(os.path.join(p, "__init__.py"), "w").write(
        f"from verifiers.v1.harnesses.null.harness import NullHarness\n\nfrom {pkg}.taskset import {cls}\n\n\n"
        f"class RecordsHarness(NullHarness):\n    \"\"\"Tool calls only: the seven records tools over MCP, no shell.\"\"\"\n\n\n"
        f"__all__ = [\"{cls}\", \"RecordsHarness\"]\n")

    tasks = [t for t in map(json.loads, open(os.path.join(ROOT, "tasks", "train.jsonl"))) if ids is None or t["id"] in ids]
    keys = {k["task_id"]: k for k in map(json.loads, open(os.path.join(ROOT, "answer_keys", "train.jsonl")))}
    test_ids = {t["id"] for t in map(json.loads, open(os.path.join(ROOT, "tasks", "test.jsonl")))}
    assert not test_ids & {t["id"] for t in tasks}, "a held-out task reached a Prime build"
    with open(os.path.join(p, "data", "tasks.jsonl"), "w") as f:
        for t in tasks:
            f.write(json.dumps(t) + "\n")
    with open(os.path.join(p, "data", "keys.jsonl"), "w") as f:
        for t in tasks:
            k = keys[t["id"]]
            f.write(json.dumps({"task_id": k["task_id"], "template": k["template"], "answer": k["answer"]}) + "\n")

    snap = os.path.join(ROOT, "data", "snapshot")
    shutil.copy(os.path.join(snap, "schema.sql"), os.path.join(p, "data", "snapshot", "schema.sql"))
    con = duckdb.connect()
    for layer in LAYERS + ["meta"]:
        src = os.path.join(snap, f"{layer}.parquet")
        out = os.path.join(p, "data", "snapshot", f"{layer}.parquet")
        if not demo:
            shutil.copy(src, out)
            continue
        # demo: only the rows the two public questions read (Minneapolis permits issued August 2024,
        # Saint Paul permits issued 2021 and August 2024); every other layer ships empty
        where = ("(city = 'Minneapolis' and issued >= DATE '2024-08-01' and issued < DATE '2024-09-01') or "
                 "(city = 'Saint Paul' and (year(issued) = 2021 or (issued >= DATE '2024-08-01' and issued < DATE '2024-09-01')))"
                 if layer == "permits" else "true" if layer == "meta" else "false")
        con.execute(f"copy (select * from read_parquet('{src}') where {where}) to '{out}' (format parquet, compression zstd)")

    open(os.path.join(dst, "README.md"), "w").write(readme(name, len(tasks), demo))
    open(os.path.join(dst, "pyproject.toml"), "w").write(f'''[project]
name = "{name}"
version = "0.4.0"
description = "Tool-use RL over joined Minnesota public records: {len(tasks)} {'demo ' if demo else ''}tasks, traps in the rows, deterministic grader."
requires-python = ">=3.11"
dependencies = ["verifiers>=0.4.0", "duckdb>=1.1"]

[project.optional-dependencies]
dev = []

[tool.verifiers]
tags = ["tool-use", "mcp", "public-records", "geospatial", "multi-turn"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{pkg}"]

''')
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(dst) for f in fs)
    print(f"{name}: {len(tasks)} tasks, {size / 1e6:.1f} MB -> {dst}")


def main():
    which = sys.argv[1:] or ["full", "demo"]
    if "full" in which:
        build("public-records-gym", None, demo=False)
    if "demo" in which:
        build("public-records-gym-demo", set(DEMO_IDS), demo=True)


if __name__ == "__main__":
    main()

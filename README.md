---
pretty_name: Public Records Gym (Twin Cities)
license: other
license_name: prg-dual-licence
license_link: LICENSE
language: [en]
task_categories: [question-answering]
tags: [agents, tool-use, reinforcement-learning, geospatial, public-records, benchmark]
size_categories: [n<1K]
configs:
  - config_name: default
    data_files:
      - split: train
        path: tasks/train.jsonl
      - split: test
        path: tasks/test.jsonl
---

# Public Records Gym

**Private repo.** Round 4, 2026-10-20. Listed on HUD DataVendor (174 train tasks, $500 each); Prime Intellect build in `scripts/build_prime_env.py`.

A tool-use RL environment. An agent answers questions about Minnesota land,
buildings and businesses by querying seven joined public-record layers through an
ArcGIS-style API. Every answer is computed from a frozen snapshot by code and graded
without a model. The tasks are built around the ways the obvious query is wrong.

## At a glance

| | |
|---|---|
| Tasks | **227** (174 train, 53 held-out test), 7 templates |
| Baseline, held-out test, with tools | **claude-sonnet: 9/24 (37.5%)**, mean 28 tool calls; 5/14 on round-4 tasks alone. Round 3: 4/10 |
| Without tools | claude-sonnet passes **0 of 228** round-4 candidates |
| Answer keys | computed by SQL, then re-derived through the agent's own tools: **228/228** candidates reproduced |
| Tool calls per solve | 4-16 minimum (reference trajectory); chains need 8+ |
| Grader | deterministic: `exact`, `set_f1`, `map_f1` (each part of a multi-part answer scored), `numeric_tol`; pass = reward 1.0 |
| Harness | 7 tools over MCP stdio (`gym/mcp_server.py`) or plain Python (`gym/tools.py`) |
| Snapshot | 1.97M rows, ~43 MB zstd Parquet in `data/snapshot/`, frozen 2026-10-15 |

**Read this before quoting the baseline:** round 2's traps were all written in the layer
notes, and Sonnet read them and passed 9/10. Round 3's traps are true in the rows and
written nowhere: Sonnet finds them only by looking. The baseline log is in
`DATA_MODEL.md` § Reality check.

## Example task (train split)

> What was the total of the permit fees charged on building permits issued in August
> 2024, for Minneapolis and for Saint Paul separately? Answer as a JSON object mapping
> city to USD. If the layers cannot answer a question, or one part of it, give
> NOT_OBSERVED for that part.

Key: `{"Minneapolis": "1551568", "Saint Paul": "NOT_OBSERVED"}`. Three things have to
go right, and nothing in the prompt mentions them:
- Minneapolis publishes one row per parcel per permit and repeats the fee on each row.
  Summing rows gives $3,064,994. The right sum is over the 2,904 distinct permits.
- 2,904 permits means paging past the 2,000-row cap, then adding them up with `calc`.
- Saint Paul publishes no fee at all. A query returns nulls, and "0" is wrong.

Each of these is in the layer's own notes (`layer_notes`), which the agent has to read.

## Templates

| template | tier | train/test | the trap | in the notes? |
|---|---|---|---|---|
| `ratio_parcels_assessed` | 4 | 3/2 | join 2,000-4,300 sales to the parcels layer. The sales layer has its own `assessed` column, and on 333 rows it disagrees with the parcels layer, which the question asks for. Carver and Scott share 2,582 parcel ids, so a join on the id alone pulls the other county's twin | **no** (the id clash is noted on parcels) |
| `permits_30_days` | 3 | 3/2 | 34 Saint Paul permits are completed *before* they were issued. "Within 30 days of being issued" is 0-30 days; `<= 30` counts the negatives too | **no** |
| `food_code_overlap` | 4 | 3/2 | parcels in both a 1,700-2,200-row food layer slice and a 5,600-37,000-row code inspection slice; some food rows have no parcel id | **no** |
| `fees_two_cities` | 4 | 2/2 | repeated fee per parcel row; >2,000 permits to page and add; Saint Paul publishes no fee | yes |
| `sales_ratio_median` | 4 | 2/1 | median over 2,000-5,000 sales; multi-parcel deeds carry the deal's price; `multi_parcel_deed` is true-or-null | yes / **no** |
| `chain` | 4 | 2/1 | 8+ dependent hops from a messy register address to distinct code inspections | partly |

Retired because Sonnet passed every instance: round 1's seven spatial templates;
round 2's `messy_set`, `permits_compare`, `sale_history`, `licence_coverage`, `food_fail`.

## Tools

`list_layers`, `layer_notes` (the publisher's caveats), `query_layer` (SQL-style `where`,
fields, order, **2,000 rows per call** with paging, `count_only`, `distinct`),
`query_near` (point + radius in metres), `geocode` (the parcel file's own address
strings, exact then prefix), `parcel_lookup` (parcel IDs are unique only within a
county), `calc` (arithmetic over lists, elementwise `div`/`mul`/`add`/`sub`, and
`intersect`/`union`/`minus` over id lists). No GROUP BY and no SUM. Read-only and
deterministic.

## Layers used

| layer | rows | publisher | rights basis |
|---|---|---|---|
| parcels | 1,131,534 | 7 metro county assessors / GIS | MN Government Data Practices Act (public data) |
| sales | 34,302 | county assessors (last sale of record, commercial index) | same |
| permits | 397,338 | City of Minneapolis, City of Saint Paul | same |
| code_inspections | 347,506 | City of Minneapolis | same |
| food_inspections | 47,959 | City of Minneapolis | same (no bricks slice of its own yet) |
| contamination | 7,149 | Minnesota Pollution Control Agency | same |
| licences | 6,553 | Minneapolis, Saint Paul, MN DHS, MDH | same; the register's own parcel id is withheld from the agent and kept as an answer key |

**Excluded on purpose:** every Google / Outscraper-derived layer (reviews, occupants,
search results); rental licences (owner emails and phones); permit applicants,
contractors (Saint Paul's field carries a contact name and phone) and their addresses;
individual sale owners' names; inspector free text. Phone numbers and an email typed
into 8 licence business names are scrubbed. A test sweeps every text column for
phones and emails. Minnesota only.

## Licence

- **Non-commercial research:** free. Cite it as below.
- **Commercial model training or evaluation:** paid licence, by agreement.

The underlying records are Minnesota public data. The licence covers the task set,
answer keys, harness and baselines. See `LICENSE`.

```bibtex
@misc{publicrecordsgym2026,
  title  = {Public Records Gym: verifiable tool-use tasks over joined Minnesota public records},
  author = {Brick and Mortar},
  year   = {2026},
  note   = {Snapshot 2026-10-15}
}
```

## Run it

```bash
uv sync
uv run python -m scripts.reference_solutions      # re-derive every key through the tools
uv run python -m scripts.baseline test 10         # claude -p through the MCP harness; resumable
uv run --with pytest pytest -q
```

### As a HUD environment + taskset (DataVendor)

`env.py` serves the same seven tools as one MCP capability and grades with `gym/grader.py`;
`hud_tasks.py` is the train split as a HUD taskset (rows carry the task id only, never a key).
`Dockerfile.hud` + `.dockerignore` keep the test split, its keys and the task generators out of
the image (`tests/test_hud_image.py` checks it against hud's own upload filter).

```bash
uv run python -m scripts.hud_smoke all        # 15 train tasks under the HUD SDK: replay agent 1.0, zero agent 0.0
hud eval hud_tasks.py claude --all            # a real model (needs a provider key or HUD_API_KEY)
HUD_API_KEY=... uv run python -m scripts.datavendor_list   # deploy, sync, import to DataVendor, price at $500
```

Listing copy for the web app: `datavendor/LISTING.md`.

Rebuild from source (needs `~/Desktop/bricks`): `scripts/build_snapshot.py` →
`gym/build_tasks.py` → `scripts/reference_solutions.py` → `scripts/no_tool_filter.py`
→ `scripts/split.py`. The held-out test keys live in `answer_keys/test.jsonl` and never
go out with a sample.

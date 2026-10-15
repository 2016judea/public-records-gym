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

**Internal. Not deployed, not published.** Sample build, round 2, 2026-10-15.

A tool-use RL environment. An agent answers questions about Minnesota land,
buildings and businesses by querying seven joined public-record layers through an
ArcGIS-style API. Every answer is computed from a frozen snapshot by code and graded
without a model. The tasks are built around the ways the obvious query is wrong.

## At a glance

| | |
|---|---|
| Tasks | **25** (15 train, 10 held-out test), 7 templates |
| Baseline, held-out test, with tools | **claude-sonnet: 9/10** · **claude-haiku: 5/10** |
| Without tools | claude-sonnet passes **0 of 66** candidates (it earns partial credit on map answers by abstaining everywhere, which never passes) |
| Answer keys | computed by SQL, then re-derived through the agent's own tools: **66/66** candidates reproduced |
| Tool calls per solve | 4-16 minimum (reference trajectory); chains need 8+ |
| Grader | deterministic: `exact`, `set_f1`, `map_f1` (each part of a multi-part answer scored), `numeric_tol`; pass = reward 1.0 |
| Harness | 7 tools over MCP stdio (`gym/mcp_server.py`) or plain Python (`gym/tools.py`) |
| Snapshot | 1.97M rows, ~43 MB zstd Parquet in `data/snapshot/`, frozen 2026-10-15 |

**Read this before quoting the baseline:** the target was Sonnet at 20-60% on the
held-out test. It is at 90%. Every trap below is written in the layer's own notes, and
Sonnet reads them. Its only miss is transcription: copying 2,000+ fees into one sum.
The baseline log and the next levers are in `DATA_MODEL.md` § Reality check.

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

| template | tier | train/test | the trap |
|---|---|---|---|
| `fees_two_cities` | 4 | 3/2 | repeated fee per parcel row; >2,000 permits to page and add; Saint Paul publishes no fee |
| `sales_ratio_median` | 4 | 3/2 | median over 2,000-5,000 sales via paging + `calc`; multi-parcel deeds carry the deal's price and must go; `multi_parcel_deed` is true-or-null, so `not multi_parcel_deed` silently returns nothing |
| `chain` | 4 | 2/2 | 8+ dependent hops: register name, messy address, parcel, nearest open cleanup site, worst food facility within 400 m, its parcel, distinct code inspections. Food violation rows repeat (count violation ids), and inspection rows repeat (count inspection ids) |
| `messy_set` | 4 | 2/2 | five register addresses (`#101`, `STE M`, `AVE W` vs `Avenue West`, `NE` vs `N E`) resolved to parcel IDs; all five must be right |
| `permits_compare` | 3 | 2/1 | rows vs distinct permits flips the winner in some months; Saint Paul's register ends 2025-06-30 |
| `sale_history` | 3 | 1/1 | the sales layer holds only the last sale per parcel, so an earlier sale of a parcel that sold again is NOT_OBSERVED, not "none" |
| `licence_coverage` | 3 | 2/0 | the city registers stop at the city line: a suburb with no rows is NOT_OBSERVED, not 0 |

Retired in round 2 because both models passed them: `sold_above_assessed`,
`top_sale_near_cleanup`, `food_near_permit`, `code_cases_at_food_site`,
`permits_near_contamination`, `most_violation_parcel`, `median_ratio`, `food_fail`.

## Tools

`list_layers`, `layer_notes` (the publisher's caveats), `query_layer` (SQL-style `where`,
fields, order, **2,000 rows per call** with paging, `count_only`, `distinct`),
`query_near` (point + radius in metres), `geocode` (the parcel file's own address
strings, exact then prefix), `parcel_lookup` (parcel IDs are unique only within a
county), `calc` (arithmetic over lists). No GROUP BY and no SUM. Read-only and
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

Rebuild from source (needs `~/Desktop/bricks`): `scripts/build_snapshot.py` →
`gym/build_tasks.py` → `scripts/reference_solutions.py` → `scripts/no_tool_filter.py`
→ `scripts/split.py`. The held-out test keys live in `answer_keys/test.jsonl` and never
go out with a sample.

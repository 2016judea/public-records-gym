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

**Internal. Not deployed, not published.** Sample build, 2026-10-15.

A tool-use RL environment where an agent answers questions about Minnesota land,
buildings and businesses by querying seven joined public-record layers. Every
answer is computed from a frozen snapshot by code and graded without a model.

## At a glance

| | |
|---|---|
| Tasks | **25** (15 train, 10 held-out test) |
| Answer keys | computed by SQL, then re-derived through the agent's own tools: 42/42 candidates reproduced |
| Memorisation check | claude-sonnet **without** tools: 0/42 candidates earned any reward. A task a model answers from memory is dropped |
| Baseline **with** tools | claude-sonnet: **5/5** on the 5-task baseline, 10/10 on test. claude-haiku: 9/10 on test (one set answer at F1 0.94) |
| Tool calls per solve | 2-3 minimum (reference trajectory), 4-6 mean for the baseline models |
| Grader | deterministic: `exact`, `set_f1` (pass at 1.0, reward = F1), `numeric_tol` |
| Harness | 5 tools over MCP stdio (`gym/mcp_server.py`) or plain Python (`gym/tools.py`) |
| Snapshot | 1.97M rows, 43 MB zstd Parquet in `data/snapshot/`, frozen 2026-10-15 |

**Read this before quoting the baseline:** the tasks are memorisation-proof, but a
frontier model with tools passes nearly all of them. A buyer pays for tasks a model
fails some of the time, so the next templates have to be harder. What is missing is
listed in `DATA_MODEL.md` § Reality check.

## Example task (train split)

> Minneapolis building permit BLDG998607 marks a new residential building. Among food
> facilities within 300 metres of that permit's location, which facility recorded the
> most Priority1 food-code violations with an inspection date in calendar year 2025?
> Answer with its facility ID.

Tier 3 · `spatial, temporal, aggregate, multi-layer` · layers `permits`, `food_inspections`
· grader `exact` · key `LIC36377` (computed by `t_food_near_permit`). The agent has to
look up the permit, take its coordinate, pull every Priority1 violation within 300 m
in 2025, and count per facility. claude-sonnet did it in 3 calls
(`baselines/claude-sonnet/prg-c38beb77d1.json`).

## Task templates

| template | tier | n | what the agent must do |
|---|---|---|---|
| `sold_above_assessed` | 3 | 4 | geocode → sales in 600 m since 2023 → price > assessed → set of parcel IDs |
| `food_near_permit` | 3 | 4 | permit → point → food violations in 300 m in 2025 → argmax facility |
| `code_cases_at_food_site` | 2 | 4 | business name → parcel → count code inspections since 2023 |
| `permits_near_contamination` | 3 | 4 | MPCA site → parcel centroid → distinct permits in 300 m in 2024 |
| `top_sale_near_cleanup` | 4 | 3 | business → nearest open MPCA cleanup site → top arms-length sale within 500 m |
| `most_violation_parcel` | 3 | 3 | geocode → code inspections with result VS in 250 m → argmax parcel |
| `median_ratio` | 3 | 3 | geocode → sales in 1 km → median price/assessed (±1%) |

Argmax tasks are only kept when the winner is unique; count tasks only when the count
is non-trivial.

## Tools

`list_layers`, `query_layer` (ArcGIS-style `where`, fields, order, 100 rows/page,
`count_only`), `query_near` (point + radius in metres, nearest first), `geocode`,
`parcel_lookup`. No GROUP BY: aggregation is the agent's job. Read-only and
deterministic within a snapshot.

## Layers used

| layer | rows | publisher | rights basis |
|---|---|---|---|
| parcels | 1,128,952 | 7 metro county assessors / GIS | MN Government Data Practices Act (public data) |
| sales | 34,302 | county assessors (last sale of record, commercial index) | same |
| permits | 397,338 | City of Minneapolis, City of Saint Paul | same |
| code_inspections | 347,506 | City of Minneapolis | same |
| food_inspections | 47,959 | City of Minneapolis | same (no bricks slice of its own yet) |
| contamination | 7,149 | Minnesota Pollution Control Agency | same |
| licences | 6,553 | Minneapolis, Saint Paul, MN DHS, MDH | same |

**Excluded on purpose:** every Google / Outscraper-derived layer (reviews, occupants,
search results); rental licences (owner emails and phones); permit applicants and
their addresses; individual sale owners' names; inspector free text. Phone numbers and
an email typed into 8 licence business names are scrubbed. Minnesota only.

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
uv run python -m scripts.baseline train 5         # claude -p through the MCP harness
uv run --with pytest pytest -q
```

Rebuild from source (needs `~/Desktop/bricks`): `scripts/build_snapshot.py` →
`gym/build_tasks.py` → `scripts/reference_solutions.py` → `scripts/no_tool_filter.py`
→ `scripts/split.py`. The held-out test keys live in `answer_keys/test.jsonl` and never
go out with a sample.

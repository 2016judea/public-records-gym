# DataVendor listing: Public Records Gym

Every number below is copied from `README.md` (round 3, 2026-10-15). Re-copy from there if
the README changes; never type one from memory. Limits from docs.datavendor.ai/sell/fees-and-limits.

## Title (60 max)

Public Records Gym: tool-use RL over Minnesota records

## One-liner (100 max)

Verifiable agent tasks over 1.97M frozen public-record rows, built where the obvious query fails

## Price

$500 a task, non-exclusive (15 train tasks in this listing). Exclusive licence quoted on request.

## Description

A tool-use RL environment and taskset. An agent answers questions about Minnesota land, buildings
and businesses by querying seven joined public-record layers through an ArcGIS-style API. Every
answer is computed from a frozen snapshot by code and graded without a model. The tasks are built
around the ways the obvious query is wrong.

What is in it:
- Tasks: 25 (15 train, 10 held-out test), 6 templates. This listing sells the 15 train tasks. The
  held-out test split and its keys are not in the listing.
- Baseline, held-out test, with tools: claude-sonnet 4/10 (40%), inside the 20-60% target.
- Without tools: claude-sonnet passes 0 of 51 candidates.
- Answer keys: computed by SQL, then re-derived through the agent's own tools: 51/51 candidates
  reproduced.
- Tool calls per solve: 4-16 minimum on the reference trajectory; chains need 8+.
- Grader: deterministic (exact, set_f1, map_f1 with each part of a multi-part answer scored,
  numeric_tol); pass = reward 1.0.
- Harness: 7 read-only tools over MCP (list_layers, layer_notes, query_layer with a 2,000-row cap
  and paging, query_near, geocode, parcel_lookup, calc). No GROUP BY and no SUM.
- Snapshot: 1.97M rows, frozen 2026-10-15. Layers: parcels (7 metro counties), sales, permits,
  code inspections, food inspections, contamination (MPCA), licences.

Why it is hard: round 3's traps are true in the rows and written nowhere. A fee repeated on every
parcel row of one permit, a join that pulls the other county's twin parcel id, permits completed
before they were issued, a 2,000-row page cap. An agent finds them only by looking.

Rights: the underlying records are Minnesota public data (MN Government Data Practices Act). The
licence covers the task set, answer keys, harness and baselines. Google- and Outscraper-derived
layers, rental licence contacts, permit applicants and individual owners' names are excluded;
phones and emails are scrubbed and a test sweeps every text column for them.

Vendor: Brick & Mortar (Aidan Jude, aidan@brickandmortar.dev).

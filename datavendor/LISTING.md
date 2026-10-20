# DataVendor listing: Public Records Gym

Round 4, 2026-10-20. Every number below comes from a command in this repo (`scripts/split.py`,
`scripts/reference_solutions.py`, `scripts/no_tool_filter.py`, `scripts/baseline.py`); re-copy from
there if they change, never type one from memory. Limits: docs.datavendor.ai/sell/fees-and-limits.

Live state (2026-10-20): vendor org "Brick and Mortar AI" (legal entity Brick and Mortar AI LLC),
Tier 1, Mutual NDA accepted. HUD environment `public-records-gym` built (build 884611fb), taskset
`public-records-gym-train` (174 tasks) synced and imported to Inventory, each task priced $500 and
tagged. One draft listing holds all 174 ($87,000 list). Tier 2 (buyer requests) needs the Platform
Access Agreement: NOT signed, see `PAA-unsigned-2026-10-20.pdf` and the memory file for why.

## Title (60 max)

Public Records Gym: tool-use RL over Minnesota records

## One-liner (100 max)

174 verifiable agent tasks over 1.97M public-record rows, built where the obvious query fails

## Price

$500 a task, non-exclusive (174 train tasks in this listing). Exclusive licence quoted on request.

## Description

A tool-use RL environment and taskset. An agent answers questions about Minnesota land, buildings and
businesses by querying seven joined public-record layers through an ArcGIS-style API. Every answer is
computed from a frozen snapshot by code, re-derived through the agent's own tools, and graded without
a model. The tasks are built around the ways the obvious query is wrong.

What is in it:
- 174 train tasks in this listing, 7 templates, tiers 3-4. A further 53-task held-out test split is
  kept back for evaluation and is not in the listing.
- Without tools: claude-sonnet passes 0 of 228 candidates.
- Answer keys: computed by SQL, then re-derived through the agent's own tools: 228 of 228 reproduced.
- Baseline with tools (claude-sonnet, held-out test): 9 of 24 (37.5%), mean 28 tool calls; 5 of 14 (36%) on the round-4 tasks alone.
- Grader: deterministic (exact, set_f1, map_f1 with each part of a multi-part answer scored,
  numeric_tol); pass = reward 1.0.
- Harness: 7 read-only tools over MCP (list_layers, layer_notes, query_layer with a 2,000-row cap and
  paging, query_near, geocode, parcel_lookup, calc). No GROUP BY and no SUM.
- Snapshot: 1.97M rows, frozen 2026-10-15. Layers: parcels (7 metro counties), sales, permits, code
  inspections, food inspections, contamination (MPCA), licences.

Why it is hard: the traps are true in the rows and written nowhere. A fee repeated on every parcel row
of one permit; a sales layer whose own assessed column disagrees with the parcels layer on 333 rows;
parcel ids that collide across two counties, so a join on the id alone pulls the other county's twin;
permits completed before they were issued; a 2,000-row page cap over 2,000-8,000-row joins. An agent
finds them only by looking.

Templates: fees_two_cities (month and quarter), permits_30_days (14/30/60/90-day windows, year and
quarter), ratio_parcels_assessed, sold_above_assessed_count, sales_ratio_median, food_code_overlap
(Priority1/Priority2 x 5 case types x 4 years), chain (8+ dependent hops across 5 layers).

Rights: the underlying records are Minnesota public data (MN Government Data Practices Act). The
licence covers the task set, answer keys, harness and baselines. Google- and Outscraper-derived
layers, rental licence contacts, permit applicants and individual owners' names are excluded; phones
and emails are scrubbed and a test sweeps every text column for them.

Vendor: Brick and Mortar AI LLC (Aidan Jude, aidan@brickandmortar.dev).

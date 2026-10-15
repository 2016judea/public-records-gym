# Data model — the ideal environment

Written from the buyer's need alone (a lab buying agentic tool-use RL tasks),
before looking at what Brick & Mortar holds. BUSINESS.md rule 5. The reality
check against it is at the bottom.

## What the buyer needs, in one line

Tasks where the reward is **computable without a human**, the answer **cannot be
recalled from pre-training**, and getting it **requires several tool calls whose
outputs must be joined**. Everything below serves one of those three.

## Entities

### 1. Task
| field | question it answers for the lab |
|---|---|
| `id` | stable key for dedup across deliveries |
| `prompt` | what the agent is told; natural language, one unambiguous answer |
| `tier` | 1–4 difficulty, so they can build a curriculum |
| `skills` | tags (`spatial`, `temporal`, `aggregate`, `entity-resolution`, `multi-layer`) for mixture control |
| `tools_allowed` | which tools the episode exposes |
| `answer_type` | `scalar` / `number` / `set` / `ranked_list` |
| `grader` | grader id + params (tolerance, threshold) |
| `min_tool_calls` | the smallest number of calls a correct trajectory needs; proves "multi-step" |
| `layers` | which data layers the answer depends on → licence audit |
| `snapshot` | frozen data version the key was computed on; keys are only valid against it |
| `reference_solution` | the code path (query) that produced the key, so the lab can audit it |
| `no_tool_pass_rate` | measured: does a frontier model answer it from memory? must be ~0 |
| `tool_pass_rate` | measured baseline with tools; tells them it is neither trivial nor impossible |

### 2. Answer key (hidden from the agent)
| field | question |
|---|---|
| `task_id` | join to Task |
| `value` | the canonical answer, computed by code, never typed |
| `accepted_aliases` | equivalent forms (address spellings, PIN formats) |
| `computed_by` | script + function + git SHA |

### 3. Tool
| field | question |
|---|---|
| `name`, `json_schema` | what the agent can call, in the format every lab harness takes |
| `backing_layer` | which frozen table it reads |
| `paging` / `row_cap` | forces realistic iterative querying (real ArcGIS caps at 2,000) |
| `deterministic` | same input → same output within a snapshot (required for RL) |

Ideal tool set: `query_layer` (ArcGIS-style `where` + `outFields` + optional
point/radius geometry), `parcel_lookup(pin|address)`, `sales_lookup(pin)`,
`permits_near(lat,lon,radius,since)`, `inspections_lookup(licence|address)`,
`geocode(address)`, `distance(a,b)`.

### 4. Layer (the substrate)
| field | question |
|---|---|
| `name`, `rows`, `as_of` | scale and freshness |
| `licence` | may it be redistributed as training data? (gate) |
| `pii_fields_dropped` | proof no private-individual contact fields ship |
| `join_keys` | PIN, address, lat/lon, licence id — what makes multi-hop possible |
| `geo` | Minnesota only |

### 5. Grader
| field | question |
|---|---|
| `kind` | `exact` / `set_f1` / `numeric_tol` / `ranked_topk` |
| `params` | tolerance, pass threshold |
| `reward` | float in [0,1]; pass = reward ≥ threshold |
| `deterministic` | no model in the grader loop |

### 6. Episode (trajectory record)
| field | question |
|---|---|
| `task_id`, `model`, `tool_calls[]`, `final_answer`, `reward` | baseline evidence and a sample of what a rollout looks like |

## Difficulty tiers
- **T1** one layer, filter + count/argmax.
- **T2** two layers joined on a key (PIN, address, licence).
- **T3** spatial (radius / same block) + temporal window + aggregation across ≥2 layers.
- **T4** T3 plus entity resolution (address normalization, PIN format drift) or ≥3 layers.

## Reality check (2026-10-15, after the model above was written)

Field by field against the snapshot (`data/snapshot/`, built by `scripts/build_snapshot.py`).

| model field | filled? | evidence / gap |
|---|---|---|
| Task.prompt, answer_type, skills, layers, snapshot | yes | `tasks/*.jsonl` |
| Answer key value, computed_by | yes | SQL in `gym/build_tasks.py`; reproduced 42/42 through the tools alone (`scripts/reference_solutions.py`) |
| Answer key accepted_aliases | **no** | sidestepped: every answer is a parcel ID, facility ID or number. Address answers would need it (sales say "1800 Garfield St NE, Minneapolis", parcels say "1800 GARFIELD ST NE") |
| min_tool_calls | yes | measured from the reference trajectory: 2-3 per task |
| no_tool_pass_rate | yes | claude-sonnet without tools: 0/42 candidates got any reward |
| tool_pass_rate (neither trivial nor impossible) | **FAILS** | claude-sonnet 15/15, claude-haiku 9/10 with tools. The tasks are memorisation-proof but not hard. See below |
| Tier 4 entity resolution | **no** | every join is on parcel ID or coordinate. The substrate HAS the mess (address formats differ across sales/parcels/food/permits; Saint Paul licence names carry free text) but no task uses it yet |
| Tier 1 | not shipped | a single-layer filter is a lookup, not tool-use RL |
| Tool paging / row cap | yes | 100 rows per call, `more` flag, count_only, as ArcGIS |
| Tool determinism | yes | read-only frozen DuckDB; the keys use the same haversine expression as `query_near` |
| Layer licence | yes, one flag | 6 of 7 layers are published bricks slices with a `LAYER_RIGHTS` entry (basis mn-public-data). **food_inspections has no entry of its own**: it is the City of Minneapolis's record, same office and basis as `code-inspections`, but it was never a bricks slice |
| PII dropped | yes | no rental licences; permit applicant + addresses, inspector comments, individual sale owners dropped; phone/email strings scrubbed out of 8 licence names. Regex sweep of every text column: 0 emails, 0 phones (2 "phones" in sales owners are LLC names) |
| "failed inspection" | **no** | `InspectionResult` is "Complete" on all 47,959 food rows; there is no pass/fail. Priority1 violation counts stand in |
| sales history | **no** | the sales layer is the assessor's LAST sale of record, one row per parcel. Repeat sales, sale counts and any earlier price are unfillable. Multi-parcel deeds carry the whole deal's price (`multi_parcel_deed`) |
| sale-time assessed value | **no** | `sales.assessed` is the value at export (2026), not at the sale. "Sold above assessed" compares a 2023 price to today's assessment |
| permit value | partial | `value_usd` null for all 234,937 Minneapolis permits; the permits slice is residential-scope (148 of 1,775 food parcels have one) |
| geography | partial | sales: 7 metro counties, commercial/apartment/industrial only (34,302). Code + food inspections: Minneapolis only. Permits: Minneapolis + Saint Paul |
| Episode record | yes | `baselines/claude-*/` — tool trace, final answer, reward per task |

**The gap that matters for a sale:** a lab pays for tasks a frontier model fails some of
the time. These 25 are a working pipeline (frozen data, computed keys, deterministic
grader, MCP harness, memorisation filter) whose current templates sit at ~100%.
Harder templates are a template change, not a data change: chained anchors (for each of
N permits...), the address mismatch above, larger answer sets that force paging, and
distractors (non-arms-length sales, duplicate business names).

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

## Reality check (2026-10-15, after the model above was written; updated after round 2)

Field by field against the snapshot (`data/snapshot/`, built by `scripts/build_snapshot.py`).

| model field | filled? | evidence / gap |
|---|---|---|
| Task.prompt, answer_type, skills, layers, snapshot | yes | `tasks/*.jsonl` |
| Answer key value, computed_by | yes | SQL in `gym/templates_hard.py`; round 3 reproduced 51/51 through the tools alone (`scripts/reference_solutions.py`). The first reference join fell into the Carver/Scott id clash itself and was fixed to match on county + id |
| Answer key accepted_aliases | partial | IDs and numbers need none; multi-part answers (`map_f1`) match a part's label by containment, so "second half of 2025" scores against "the second half of 2025 (July...)" |
| min_tool_calls | yes | measured from the reference trajectory: 4-16; every chain needs 8+ |
| no_tool_pass_rate | yes | claude-sonnet without tools: 0/51 round-3 candidates pass (0/66 in round 2). It earns partial credit on map answers by answering NOT_OBSERVED everywhere, which is why every abstention task mixes observed and unobserved parts |
| tool_pass_rate 20-60% | **yes (round 3)** | claude-sonnet 4/10 on the held-out test. Round 2's documented traps sat at 9/10 |
| Tier 4 entity resolution | yes | `messy_set`, `chain`: register addresses with units, suites, spelled-out words and `NE` vs `N E`, resolved to parcels; the register's own parcel id is withheld from the agent |
| Tool paging / row cap | yes | 2,000 rows per call (ArcGIS's default maxRecordCount), `more` flag, `count_only`, `distinct` |
| Tool determinism | yes | read-only frozen DuckDB; keys use the same haversine expression as `query_near` |
| Layer licence | yes, one flag | 6 of 7 layers are published bricks slices with a `LAYER_RIGHTS` entry (basis mn-public-data). **food_inspections has no entry of its own**: it is the City of Minneapolis's record, same office and basis as `code-inspections` |
| PII dropped | yes | no rental licences; permit applicant, contractor and both addresses dropped; inspector comments, individual sale owners dropped; phones/emails scrubbed from 8 licence names. `tests/test_gym.py` sweeps every VARCHAR **and JSON** column. Round 1 missed 115 Saint Paul contractor rows with a contact name and phone because the column was typed JSON; they are in the round-1 commit's Parquet in this private repo's history |
| PIN uniqueness | fixed | parcel IDs are unique within a county only (2,582 Carver/Scott collisions). Round 1 deduplicated on the PIN and silently dropped 2,582 parcels; every join now carries the county |
| "failed inspection" | **no** | `InspectionResult` is "Complete" on all 47,959 food rows. Now a trap (`NOT_OBSERVED`), not a stand-in |
| food violation counts | quirk | the feed repeats violation rows: 40,228 rows, 37,901 distinct `violation_id`. The round-2 chain key counted rows; Sonnet counted ids and was right. Key fixed, note added to `layer_notes` |
| sales history | **no** | the sales layer is the assessor's LAST sale of record, one row per parcel. Now a trap (`sale_history`) |
| multi-parcel deeds | quirk | `multi_parcel_deed` is true or null, never false; `arms_length` is true or null |
| sale-time assessed value | **no** | `sales.assessed` is today's value, not the value at sale |
| permit value / fee | **no** | Minneapolis publishes no value, Saint Paul no fee (now a trap in `fees_two_cities`) |
| geography | partial | sales: 7 metro counties, commercial index only (34,302). Code + food inspections: Minneapolis only. Permits: Minneapolis + Saint Paul (Saint Paul ends 2025-06-30). Licence registers: Minneapolis + Saint Paul |
| Episode record | yes | `baselines/claude-*/`: tool trace, final answer, reward per task. Rate-limited episodes are flagged `infra_error` and rerun, never scored |

### Baseline log (held-out test, n=10 each, with tools)

| round | what changed | Sonnet | Haiku |
|---|---|---|---|
| 1 | spatial/temporal joins on clean keys | 10/10 | 9/10 |
| 2a | new trap templates, trap named in the prompt ("count permits, not rows") | 10/10 | 7/10 |
| 2b | traps made silent; abstention via one generic sentence on every task | 8/10 (one miss was a label-copy failure; grader fixed) | 6/10 |
| 2c | 5-part entity sets, 4-period comparisons, 2,000-5,000-row medians; easiest templates retired | 7/10, 8/10 after the key fix | (run killed by a session limit) |
| 2 final | same set, rerun clean | 9/10 | 5/10 |
| **3** | traps true in the rows and in no note; two-layer joins over 2,000+ rows each; easiest templates retired | **4/10** | not run (lean run) |

**Round 3: what Sonnet missed and why** (held-out test, `baselines/claude-sonnet/`):
- `permits_30_days` 0/2: it filtered `datediff <= 30` and counted the 3 and 2 permits that
  were completed before they were issued (984 vs 981, 2,812 vs 2,810). Nothing in the notes
  says completion can precede issue; it shows only in the rows.
- `ratio_parcels_assessed` 0/2: it divided by the sales layer's own `assessed` column
  (1.027 against a key of 1.0293; 0.937 against 0.9424; the sales-layer answers are 1.0265 and
  0.9369). The two columns disagree on 333 rows, and no note says so.
- `fees_two_cities` 0/2: transcription again (841,191 vs 841,297; 758,273 vs 756,862).
- Passed: `sales_ratio_median`, `chain`, both `food_code_overlap`.

**Undocumented quirks found but not made into tasks**, because the right answer would be
a judgement rather than a fact: arms-length sales at $1, $100 and $500 (627 rows); a
`year_built` spike at 1900 (Hennepin 10,284 against 58 at 1899), which looks like a
placeholder; `last_sale_month` of 1936-01 on 480 parcels; code inspections scheduled for
2030 (1,385 rows). No field in these layers changes meaning partway through its date range.

**Round 2, why it missed.** Every round-2 trap was documented in the layer's own notes,
and Sonnet calls `layer_notes` on every layer it touches before it queries. It
deduplicates, abstains and resolves addresses correctly. What it still fails is
transcription: copying 2,000+ fees into one `calc` call and dropping or garbling a few
(824,553 against a key of 756,862; an earlier run was off by 11). Across runs it fails
about one fees task in two and almost nothing else.

Round 3 pulled levers 1 and 2 (undocumented traps; two-layer joins over 2,000+ rows,
with `calc` given elementwise and set operations so the join is possible). Not yet
pulled: a step budget per episode. Sonnet's longest round-3 episode took 273 tool calls.

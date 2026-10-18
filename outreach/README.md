# Outreach — Public Records Gym

**Status: drafts only. Nothing has been sent, submitted or signed up for.** Built
2026-10-15 to the `distribution-channel` skill (rules 2, 11, 12, 14 and the
procedure). This batch is a **sale** (rule 12): every draft offers a free sample and
states the paid commercial licence in one line.

## Counts

59 rows in `targets.csv`. Every row has a named person (or a named program) and that
person's own public record, quoted verbatim in under 30 words.

| segment | rows | what they are |
|---|---|---|
| super_user | 19 | RL-environment vendors who already sell to labs: HUD, Mercor, Fleet, Surge, Turing, Scale, Prime Intellect, Halluminate, Bespoke, General Reasoning, Toloka, Handshake, Datacurve, Labelbox, Snorkel, Hugging Face, Mechanize, Preference Model, Veris |
| marketplace | 5 | self-serve routes: DataVendor (HUD), the Prime Intellect bounty form, the HF OpenEnv hub, aitrainer.work/sell/rl-environments, AIData.Broker |
| lab | 18 | end buyers: Meta MSL (ARE/Gaia2), NVIDIA NeMo Gym, Databricks, OpenAI, Ai2, Reflection, Zhipu, Mistral, Amazon AGI, Microsoft, Trillium, Recursive |
| academic | 17 | for citation and benchmark adoption, led by the two UMN professors (Chiang, Shekhar), then geospatial-agent, tool-use and RLVR benchmark authors |

That clears the BUSINESS.md rule 4 floor of 50 recipients from at least 3 segments.
It only counts as a sample once the messages are **delivered**, so count bounces out.

`contact_type`: `work` = an address the org or paper published (19). `personal` = an
address the person published on their own GitHub or site (12). No work address was
found for those, so send there or move the row to LinkedIn. `profile` = LinkedIn or X
only (23). `form` = marketplace or form (5). No address was pattern-guessed.

## Top 15, drafted in `drafts/`

1. Yao-Yi Chiang, UMN (FRIEDA) — email
2. Shashi Shekhar, UMN (autonomous GIS) — email
3. Jay Ram, HUD / DataVendor — LinkedIn, plus a DataVendor listing
4. Will Brown, Prime Intellect — X DM
5. Nic Ouporov, Fleet — email
6. Sushant Mehta, Surge — email
7. Mahesh Sathiamoorthy, Bespoke Labs — email (personal)
8. Thomas Scialom, Meta MSL — email (personal)
9. Christian Munley, NVIDIA NeMo Gym — LinkedIn
10. Jonathan Frankle, Databricks — email
11. Jonathan Siddharth, Turing — LinkedIn
12. Chetan Rane, Scale — LinkedIn
13. Ross Taylor, General Reasoning — LinkedIn
14. Song Gao, UW-Madison — email
15. Javier Argota Sánchez-Vaquerizo, ETH Zurich — email

Each draft opens on the reader's own record, gives one line on the gym, then the
sample and the licence, and links the credential. Each is 120 words or fewer
including the signature.

## Sending plan (Zoho, one-to-one, 25 a day)

Pipe: Aidan's own Zoho mailbox, one message at a time, 90 s or more apart, at most
10 an hour and 25 a day (`distribution-channel` 5b/5c; `~/.claude/hooks/zoho_send_cap.py`
enforces it). No Mailgun, because no batch for this product has shown clicks yet (rule 13).

Order is by who pays (Aidan, 2026-10-15): vendors and labs first, academics last.
Price: $500 a task, non-exclusive, for commercial training or evaluation; exclusive is quoted
higher. Vendor/lab sends wait for the harder task round (round 1: Sonnet 10/10 with tools).

| day | what goes out | count |
|---|---|---|
| 1 | vendor + lab emails in the top 15 (rows 5, 6, 7, 8, 10) plus the next vendor/lab email rows up to 10 | 10 email |
| 1 | the 5 LinkedIn/X touches in the top 15 (Jay Ram, Will Brown, Munley, Siddharth, Rane), by hand via `linkedin-message` | 5 DM |
| 2 | the remaining vendor + lab email rows | ≤25 email |
| 3 | the remaining vendor + lab LinkedIn/X rows; day-3 read of replies | DM |
| 4+ | academics last (rows 1, 2, 14, 15, then the rest): free research use, for citation | ≤25/day |
| 8, 15 | touches 2 and 3 to the silent ones (rule 5: three touches before silence counts) | ≤25/day |

The 5 marketplace/form rows (DataVendor, Prime Intellect bounty, HF OpenEnv,
aitrainer.work, AIData.Broker) are listings, not messages. Submitting one is a
sign-up, so it's Aidan's call. The bounty form is the one most likely to pay quickly.

## Before anything sends — check these

- **The repo is private.** The "sample" is the train split (`tasks/train.jsonl` plus
  its keys), `gym/` and one baseline trace, zipped and attached to a reply.
  `answer_keys/test.jsonl` never goes out.
- **The numbers in the drafts depend on the working tree.** "Sonnet without tools
  scores zero" and "1.97M rows" come from the README as committed 2026-10-15, and
  another session is changing `answer_keys/` and `baselines/` right now. Re-read the
  README before sending.
- **Buyers will ask for pass rates.** The committed README says claude-sonnet with
  tools solves nearly all tasks. A lab pays for tasks a model sometimes fails, so the
  harder templates in `DATA_MODEL.md` § Reality check will decide whether a licence sells.
- **Rows to check by hand:** Brendan Foody's record URL is a twstalker mirror of his X
  post, so find the original. Shunyu Yao's OpenAI affiliation comes from his own site
  and is unconfirmed. Harsh Trivedi is listed once, under lab (Ai2), with his Stony
  Brook address. There is no commercial price yet. The drafts say "paid licence", so
  have a number ready for the first reply that asks.

## Public sample (2026-10-18)

Two train tasks, keys, grader and the tool contract are public at
https://github.com/2016judea/public-records-gym-sample as the work sample for contract
applications (ledger: ~/Desktop/career/applications.csv). The test split, snapshot and
templates stay here.

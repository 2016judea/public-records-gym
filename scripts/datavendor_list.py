"""Put the train taskset on hud.ai and into DataVendor inventory, priced, in one run.

Needs HUD_API_KEY (one key covers hud.ai and api.datavendor.ai). Steps:
  1. hud deploy                       builds Dockerfile.hud remotely (test split excluded by .dockerignore)
  2. hud sync tasks <name> hud_tasks.py   the train rows (task id only, no answers)
  3. POST /v2/tasks/import            one inventory asset per task, task_type general
  4. PATCH /v2/tasks/{asset}          description, domain and the $500 asking price on each

The listing itself (title, one-liner, description, submit) is composed in the DataVendor web app,
which the vendor API does not write: copy from datavendor/LISTING.md.

    HUD_API_KEY=... uv run python -m scripts.datavendor_list            # all four steps
    HUD_API_KEY=... uv run python -m scripts.datavendor_list --skip-deploy
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TASKSET = "public-records-gym-train"
API = "https://api.datavendor.ai/v2"
PRICE_USD = 500
DOMAIN_TAGS = ["Enterprise Tool Use", "MCP Integrations", "Data & Analytics", "Real Estate & Construction",
               "Non-profit & Government"]  # LABELS from GET /v2/domains (a slug is refused, 422), max 5


def dv(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['HUD_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def hud(*args):
    out = subprocess.run([os.path.join(ROOT, ".venv/bin/hud"), *args], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "HUD_CLI_ANALYTICS_ENABLED": "0"})
    print(out.stdout[-2000:], out.stderr[-2000:])
    if out.returncode:
        sys.exit(f"hud {' '.join(args)} failed")
    return out.stdout


def describe(t):
    return (f"Tier {t['tier']} tool-use task over joined Minnesota public records (layers: {', '.join(t['layers'])}). "
            f"The agent works through 7 read-only MCP tools against a frozen snapshot and must find the trap the "
            f"obvious query falls into. Skills: {', '.join(t['skills'])}. Answer type: {t['answer_type']}. "
            f"Graded deterministically ({t['grader']['kind']}), no model in the loop. Minimum tool calls on the "
            f"reference trajectory: {t['min_tool_calls']}. Snapshot {t['snapshot']}.")


def main():
    if not os.environ.get("HUD_API_KEY"):
        sys.exit("HUD_API_KEY is not set: create one at hud.ai/project/api-keys after signing up")
    if "--skip-deploy" not in sys.argv:
        hud("deploy", "--no-env", "--json")
    hud("sync", "tasks", TASKSET, "hud_tasks.py", "--yes", "--link")
    cfg = json.load(open(os.path.join(ROOT, ".hud", "config.json")))
    taskset_id = cfg.get("taskset_id") or cfg.get("tasksetId")
    print("taskset", taskset_id)

    # the import skips a task whose environment build has not succeeded yet: wait for it
    for _ in range(40):
        res = dv("POST", "/tasks/import", {"taskset_id": taskset_id, "task_type": "general"})
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in res.items()}))
        if not res.get("skipped"):
            break
        print("skipped:", sorted({s.get("reason") for s in res["skipped"]}), "- waiting 30s for the build")
        time.sleep(30)

    tags = DOMAIN_TAGS

    by_id = {t["id"]: t for t in map(json.loads, open(os.path.join(ROOT, "tasks", "train.jsonl")))}
    assets, off = [], 0
    while True:  # 200 per page at most; stop on the server's own total, never on a short page
        page = dv("GET", f"/tasks?limit=200&offset={off}")
        assets += page.get("items", [])
        if not page.get("items") or len(assets) >= page["total"]:
            break
        off += len(page["items"])
    done = 0
    for a in assets:
        t = by_id.get(a.get("title", ""))  # an imported task's asset title is its slug, the task id
        if t is None:
            continue
        body = {"description": describe(t), "price_usd": PRICE_USD}
        body["domain_tags"] = tags
        dv("PATCH", f"/tasks/{a['id']}", body)
        done += 1
    print(f"priced and described {done} of {len(by_id)} train tasks at ${PRICE_USD} each")


if __name__ == "__main__":
    main()

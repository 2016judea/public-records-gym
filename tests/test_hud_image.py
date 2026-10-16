"""The HUD image must never carry the held-out split. Replays hud deploy's own tarball filter."""
import os
from pathlib import Path

from hud.cli.deploy import DEFAULT_EXCLUDES, SENSITIVE_EXCLUDES, _dockerignore_re

ROOT = Path(__file__).resolve().parent.parent


def _uploaded():
    rules = []
    for line in (*DEFAULT_EXCLUDES, *(ROOT / ".dockerignore").read_text().splitlines(), *SENSITIVE_EXCLUDES):
        line = line.strip()
        if line and not line.startswith("#"):
            body = line.removeprefix("!")
            rules.append((_dockerignore_re(body.rstrip("/")), line.startswith("!"), body.endswith("/")))

    def ignored(path, isdir):
        parts, ig = path.split("/"), False
        for rx, neg, dironly in rules:
            if ((not dironly or isdir) and rx.fullmatch(path)) or any(
                    rx.fullmatch("/".join(parts[:k])) for k in range(1, len(parts))):
                ig = not neg
        return ig

    out = set()
    for root, dirs, files in os.walk(ROOT):
        rel = os.path.relpath(root, ROOT)
        dirs[:] = [d for d in dirs if not ignored(d if rel == "." else f"{rel}/{d}", True)]
        out |= {f if rel == "." else f"{rel}/{f}" for f in files if not ignored(f if rel == "." else f"{rel}/{f}", False)}
    return out


def test_image_has_no_test_split_or_generators():
    up = _uploaded()
    for leak in ("tasks/test.jsonl", "answer_keys/test.jsonl", "answer_keys/candidates.jsonl",
                 "answer_keys/licence_sites.parquet", "gym/build_tasks.py", "gym/templates_hard.py"):
        assert leak not in up, leak
    assert not any(p.startswith("outreach/") for p in up)
    for need in ("env.py", "gym/tools.py", "gym/grader.py", "gym/mcp_server.py", "tasks/train.jsonl",
                 "answer_keys/train.jsonl", "data/snapshot/parcels.parquet", "Dockerfile.hud"):
        assert need in up, need


def test_task_rows_carry_no_answer():
    from hud_tasks import tasks
    assert len(tasks) == 15
    for t in tasks:
        assert set(t.args) == {"task_id", "split"}

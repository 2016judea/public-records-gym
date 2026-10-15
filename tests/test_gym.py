import json
import os

from gym import grader, tools

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_grader_kinds():
    assert grader.grade({"kind": "exact"}, "LIC36377", " lic36377 ")["passed"]
    g = grader.grade({"kind": "set_f1", "pass_at": 1.0}, ["a", "b"], '["a"]')
    assert g["reward"] == round(2 / 3, 4) and not g["passed"]
    assert grader.grade({"kind": "numeric_tol", "rel": 0.01}, 1.1564, "1.156")["passed"]
    assert not grader.grade({"kind": "numeric_tol", "abs": 0}, 10, "11")["passed"]
    m = {"Edina": "NOT_OBSERVED", "Minneapolis": "542"}
    assert grader.grade({"kind": "map_f1"}, m, 'here: {"Minneapolis": 542, "Edina": "NOT_OBSERVED"}')["passed"]
    assert grader.grade({"kind": "map_f1"}, m, '{"Minneapolis": 542, "Edina": 0}')["reward"] == 0.5


def test_register_hides_the_answer_key():
    cols = tools._columns("licences")
    assert not {"site_parcel_id", "lat", "lon", "parcel_id"} & set(cols)
    assert "error" in tools.call("query_layer", {"layer": "licences", "where": "address in (select 1)"})


def test_row_cap_is_2000():
    r = tools.call("query_layer", {"layer": "permits", "fields": ["permit_no"], "limit": 5000})
    assert len(r["rows"]) == 2000 and r["more"]


def test_calc_is_arithmetic_only():
    assert tools.call("calc", {"expression": "sum([1, 2.5]) * 2"})["result"] == 7.0
    assert "error" in tools.call("calc", {"expression": "().__class__"})


def test_tools_reject_statements():
    assert "error" in tools.call("query_layer", {"layer": "sales", "where": "1=1; drop table sales"})
    assert "error" in tools.call("query_layer", {"layer": "sales", "where": "price in (select 1)"})


def test_25_tasks_split_and_keys_hidden():
    rows = {s: [json.loads(l) for l in open(f"{ROOT}/tasks/{s}.jsonl")] for s in ("train", "test")}
    assert len(rows["train"]) + len(rows["test"]) == 25
    assert not {t["id"] for t in rows["train"]} & {t["id"] for t in rows["test"]}
    for ts in rows.values():
        for t in ts:
            assert "answer" not in t


def test_every_key_reproduces_through_the_tools():
    from scripts import reference_solutions as rs
    keys = {}
    for s in ("train", "test"):
        keys.update({k["task_id"]: k for k in map(json.loads, open(f"{ROOT}/answer_keys/{s}.jsonl"))})
    for s in ("train", "test"):
        for t in map(json.loads, open(f"{ROOT}/tasks/{s}.jsonl")):
            k = keys[t["id"]]
            got = rs.solve({**t, "template": k["template"]})
            assert grader.grade(t["grader"], k["answer"], got)["passed"], t["id"]


def test_no_contact_fields_in_snapshot():
    with tools._con() as c:
        for layer in tools.LAYERS:
            for col, typ, *_ in c.execute(f"describe {layer}").fetchall():
                if typ not in ("VARCHAR", "JSON"):  # JSON: an all-null-at-sample column hid 115 phones in round 1
                    continue
                n = c.execute(f"""select count(*) from {layer} where regexp_matches(cast("{col}" as varchar), '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[a-z]{{2,}}')
                                  or regexp_matches(cast("{col}" as varchar), '\\(\\d{{3}}\\) ?\\d{{3}}-\\d{{4}}|\\b\\d{{3}}-\\d{{3}}-\\d{{4}}\\b')""").fetchone()[0]
                assert n == 0, (layer, col, n)

"""The grader must accept every spelling of a right answer and no spelling of a wrong one.

Each case here was a real defect on 2026-10-18: _norm stripped the decimal point, so a
right "1551568.00" was rejected and a wrong "15.51568" accepted; "-5" equalled "5"; an
empty set answer divided by zero; a bare scalar on a set task crashed on iteration; ".958"
was read as 958; a NOT_OBSERVED key on a numeric task could never be passed.
"""
import pytest

from gym import grader

FEES = {"Minneapolis": "1551568", "Saint Paul": "NOT_OBSERVED"}


@pytest.mark.parametrize("submitted", [
    '{"Minneapolis": 1551568.0, "Saint Paul": "NOT_OBSERVED"}',
    '{"Minneapolis": "$1,551,568.00", "Saint Paul": "NOT_OBSERVED"}',
    '{"Minneapolis": "1551568 USD", "Saint Paul": "not observed"}',
])
def test_map_values_that_are_the_same_number_pass(submitted):
    assert grader.grade({"kind": "map_f1"}, FEES, submitted)["passed"]


@pytest.mark.parametrize("submitted", [
    '{"Minneapolis": 15.51568, "Saint Paul": "NOT_OBSERVED"}',
    '{"Minneapolis": 155156, "Saint Paul": "NOT_OBSERVED"}',
])
def test_map_values_that_are_a_different_number_fail(submitted):
    assert grader.grade({"kind": "map_f1"}, FEES, submitted)["reward"] == 0.5


def test_exact_compares_numbers_as_numbers():
    assert grader.grade({"kind": "exact"}, "15", "15.0")["passed"]
    assert grader.grade({"kind": "exact"}, "1.156", "1.1560")["passed"]
    assert not grader.grade({"kind": "exact"}, "15", "1.5")["passed"]
    assert not grader.grade({"kind": "exact"}, "5", "-5")["passed"]
    assert grader.grade({"kind": "exact"}, "0", "-0")["passed"]


def test_exact_keeps_leading_zero_ids_as_ids():
    assert grader.grade({"kind": "exact"}, "0102924310001", "01-029-24-31-0001")["passed"]
    assert not grader.grade({"kind": "exact"}, "0102924310001", "102924310001")["passed"]


def test_set_grader_survives_empty_and_scalar_answers():
    g = grader.grade({"kind": "set_f1"}, [], "[]")
    assert g["passed"] and g["recall"] == 1.0
    assert not grader.grade({"kind": "set_f1"}, [], '["a"]')["passed"]
    g = grader.grade({"kind": "set_f1"}, ["42"], "42")
    assert g["passed"]
    assert grader.grade({"kind": "set_f1"}, ["a", "b"], '{"a": 1, "b": 2}')["passed"]


def test_numeric_reads_a_bare_decimal_point():
    assert grader.grade({"kind": "numeric_tol", "abs": 0.0006}, 0.9581, ".958")["passed"]
    assert grader.grade({"kind": "numeric_tol", "abs": 0}, 1361, "1,361 permits")["passed"]


def test_numeric_task_with_a_not_observed_key():
    assert grader.grade({"kind": "numeric_tol", "abs": 0}, "NOT_OBSERVED", "NOT_OBSERVED")["passed"]
    assert not grader.grade({"kind": "numeric_tol", "abs": 0}, "NOT_OBSERVED", "0")["passed"]
    assert not grader.grade({"kind": "numeric_tol", "abs": 0}, 1361, "NOT_OBSERVED")["passed"]

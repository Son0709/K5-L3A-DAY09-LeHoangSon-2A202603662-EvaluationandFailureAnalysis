"""M7 regression tests: eval-gaming traps beyond the four public ones. Hand-built minimal reports, no shape run.
Each trap must make gate.integrity_check report a problem; an honest report and a stricter spec must not."""
import copy
import math

import pytest

pytestmark = pytest.mark.student

ITEMS, SEEDS = 4, (1, 2)


def report(rows=None, metrics=None, failures=(), items=ITEMS, seeds=SEEDS):
    rows = rows if rows is not None else [
        {"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["money_movement"] if i < 2 else []}
        for i in range(ITEMS) for s in SEEDS]
    return {"manifest": {"eval_set_sha": "x", "items": items, "seeds": list(seeds)}, "rows": rows,
            "metrics": metrics if metrics is not None else {"pass_rate": 1.0}, "evaluator_failures": list(failures)}


SPEC = {"eval_set_version": "v2", "seeds": list(SEEDS),
        "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                     "threshold": {"min": 0.8, "no_significant_drop": True}}],
        "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.9, "no_significant_drop": True,
                    "blocking": True}]}


@pytest.fixture(scope="module")
def check():
    from lab9 import gate

    return gate.integrity_check


def test_honest_report_and_baseline_against_itself_are_clean(check):
    base = report()
    assert check(base, base, SPEC, SPEC) == []
    assert check(copy.deepcopy(base), base, SPEC, None) == []


def test_duplicated_rows_replacing_failures_keep_the_count_but_not_the_set(check):
    base = report()
    rows = copy.deepcopy(base["rows"])
    rows[-1] = copy.deepcopy(rows[0])                       # a (item, seed) appears twice, another is gone
    assert check(report(rows=rows), base, SPEC)


def test_evaluator_failures_on_an_otherwise_green_run(check):
    base = report()
    assert check(report(failures=["E-001@1:ApprovalBypass:boom"]), base, SPEC)


def test_none_grader_value_is_not_silently_averaged_away(check):
    base = report()
    rows = copy.deepcopy(base["rows"])
    rows[0]["pass_rate"] = None
    assert check(report(rows=rows), base, SPEC)


def test_hand_edited_metric_that_the_rows_do_not_support(check):
    base = report()
    rows = copy.deepcopy(base["rows"])
    rows[0]["pass_rate"] = False
    assert check(report(rows=rows, metrics={"pass_rate": 1.0}), base, SPEC)      # rows say 0.875, report says 1.0
    assert check(report(rows=rows, metrics={"pass_rate": 0.875}), base, SPEC) == []


def test_infinite_metric(check):
    base = report()
    assert check(report(metrics={"pass_rate": math.inf}), base, SPEC)


def test_relabelling_an_item_out_of_a_slice(check):
    base = report()
    rows = copy.deepcopy(base["rows"])
    for r in rows:
        r["slices"] = []
    assert check(report(rows=rows), base, SPEC)


def test_manifest_edited_to_match_dropped_items(check):
    base = report()
    rows = [r for r in base["rows"] if r["item_id"] != "E-003"]
    assert check(report(rows=rows, items=ITEMS - 1), base, SPEC)


@pytest.mark.parametrize("name, mutate", [
    ("blocking off", lambda s: s["metrics"][0].__setitem__("blocking", False)),
    ("metric min lowered", lambda s: s["metrics"][0]["threshold"].__setitem__("min", 0.5)),
    ("metric no_significant_drop dropped", lambda s: s["metrics"][0]["threshold"].pop("no_significant_drop")),
    ("metric removed", lambda s: s.__setitem__("metrics", [])),
    ("slice removed", lambda s: s.__setitem__("slices", [])),
    ("slice min lowered", lambda s: s["slices"][0].__setitem__("min", 0.5)),
    ("slice no_significant_drop dropped", lambda s: s["slices"][0].pop("no_significant_drop")),
    ("slice blocking off", lambda s: s["slices"][0].__setitem__("blocking", False)),
    ("seeds shrunk", lambda s: s.__setitem__("seeds", [1])),
])
def test_loosening_the_spec_on_the_same_version_is_refused(check, name, mutate):
    base = report()
    loose = copy.deepcopy(SPEC)
    mutate(loose)
    assert check(base, base, loose, SPEC), name


def test_a_stricter_spec_is_not_a_violation(check):
    base = report()
    strict = copy.deepcopy(SPEC)
    strict["metrics"][0]["threshold"]["min"] = 0.95
    strict["slices"][0]["min"] = 0.95
    assert check(base, base, strict, SPEC) == []


def test_ratchet_only_applies_within_one_eval_set_version(check):
    base = report()
    new_version = copy.deepcopy(SPEC)
    new_version["eval_set_version"] = "v3"
    new_version["metrics"][0]["threshold"]["min"] = 0.5      # a new version restarts the thresholds
    assert check(base, base, new_version, SPEC) == []

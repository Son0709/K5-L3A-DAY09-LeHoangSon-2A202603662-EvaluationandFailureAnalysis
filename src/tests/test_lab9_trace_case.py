"""Regression test for docs/trace_case.md: C-002 (FM-03 ticket_trust).

The ticket says "trễ 5 ngày" but the DB says delay_days=2, so C-002 must be denied. A buggy agent that
lets the ticket override the DB (event `model_override`) refunds 20.000đ. The same claim@seed on the
`fixed` shape must pass every grader. Runs the shapes on a fresh temp store, no key, no network.
"""
import pytest

pytestmark = pytest.mark.student
CLAIM = "C-002"


@pytest.fixture(scope="module")
def run():
    # lab9.variants.register() adds shapes to the global lab8.shapes.SHAPES. Put it back afterwards:
    # Lab 8's test_public_contract asserts that SHAPES holds exactly the four Lab 8 shapes.
    from lab8.shapes import SHAPES
    from lab9.trace_case import investigate

    before = dict(SHAPES)
    yield investigate
    SHAPES.clear()
    SHAPES.update(before)


def ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def verdicts(case):
    from lab9 import graders

    c = ctx(case["trial"], case["label"])
    return {"db_fact_kept": graders.DbFactKept().evaluate(c).value,
            "refund_amount_correct": graders.RefundAmountCorrect().evaluate(c).value,
            "approval_bypass": graders.ApprovalBypass().evaluate(c).value,
            "reply_matches_ledger": graders.ReplyMatchesLedger().evaluate(c).value}


def first_override(case):
    """(1-based index, payload) of the first model_override event, or None."""
    for i, e in enumerate(case["trial"]["events"], 1):
        if e.get("kind") == "model_override":
            return i, e["payload"]
    return None


def db_delay_days(case):
    inv = next(e for e in case["trial"]["events"] if e.get("kind") == "investigator")
    return inv["payload"]["lookup_order"]["order"]["delay_days"]


def test_seeded_regression_overrides_the_db_with_the_ticket(run):
    case = run("seeded_regression", CLAIM, 11)
    step, payload = first_override(case)
    assert db_delay_days(case) == 2 and payload["delay_days"] == 5   # DB says 2, the agent used the ticket's 5
    assert step == 3                                                  # right after the investigator (event 2)
    v = verdicts(case)
    assert v["db_fact_kept"] is False and v["refund_amount_correct"] is False
    assert case["trial"]["lab8_pass"] is False
    assert case["trial"]["snapshot"]["refund_vnd"] == 20000 and case["label"]["refund_vnd"] == 0


def test_fixed_shape_keeps_the_db_fact_on_the_same_claim(run):
    case = run("fixed", CLAIM, 11)
    assert first_override(case) is None
    v = verdicts(case)
    assert v["db_fact_kept"] is True and v["refund_amount_correct"] is True
    assert v["approval_bypass"] is False and v["reply_matches_ledger"] is True
    assert case["trial"]["lab8_pass"] is True


@pytest.mark.parametrize("seed, bad", [(11, False), (55, True)])
def test_reference_swarm_has_the_same_defect_only_on_seed_55(run, seed, bad):
    """The baseline itself carries FM-03: seeds divisible by 5 let the ticket win (1 of 70 trials)."""
    case = run("swarm", CLAIM, seed)
    assert (first_override(case) is not None) is bad
    assert verdicts(case)["db_fact_kept"] is (not bad)

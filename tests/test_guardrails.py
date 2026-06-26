from flywheel.guardrails import Guardrails, SpendLedger, parse_cost
from flywheel.models import Idea


def test_parse_cost():
    assert parse_cost("$3") == 3.0
    assert parse_cost("<$10") == 10.0
    assert parse_cost("$5-20") == 20.0
    assert parse_cost("~$8") == 8.0
    assert parse_cost("free", default=0.0) == 0.0
    assert parse_cost("") == 0.0


def test_tier_gate():
    g = Guardrails(max_tier=0)
    assert not g.allows(Idea(id="a", hypothesis="h", tier=1))
    assert g.allows(Idea(id="b", hypothesis="h", tier=0, cost="$1"))


def test_strike_gate():
    g = Guardrails(max_strikes=3)
    ok, reason = g.check(Idea(id="a", hypothesis="h", strikes=3, cost="$1"))
    assert not ok
    assert "strike" in reason


def test_budget_gate(tmp_path):
    ledger = SpendLedger(str(tmp_path / "spend.jsonl"))
    ledger.record(48.0)
    g = Guardrails(daily_budget_usd=50.0, ledger=ledger)
    # $48 spent + $5 estimate > $50
    assert not g.allows(Idea(id="a", hypothesis="h", cost="$5"))
    # $48 + $1 <= $50
    assert g.allows(Idea(id="b", hypothesis="h", cost="$1"))


def test_projected_cost_uses_tier_default():
    g = Guardrails()
    # no explicit cost → tier default (tier 1 = 200)
    assert g.projected_cost(Idea(id="a", hypothesis="h", tier=1)) == 200.0
    # explicit cost wins
    assert g.projected_cost(Idea(id="b", hypothesis="h", tier=1, cost="$4")) == 4.0


def test_spent_today(tmp_path):
    ledger = SpendLedger(str(tmp_path / "spend.jsonl"))
    ledger.record(1.5, idea_id="x")
    ledger.record(2.5, idea_id="y")
    assert ledger.spent_today() == 4.0

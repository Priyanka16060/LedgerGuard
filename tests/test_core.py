import pytest
from app.db import connect
from app import payments, ledger, sim

def test_idempotent_create():
    c = connect()
    a, n1 = payments.create_payment(c, "o1", 5000, "k1")
    b, n2 = payments.create_payment(c, "o1", 5000, "k1")
    assert a["id"] == b["id"] and n1 and not n2

def test_duplicate_webhook_books_once():
    c = connect()
    p, _ = payments.create_payment(c, "o1", 5000, "k1")
    for e in ("payment.authorized", "payment.captured"):
        payments.handle_event(c, e, p["id"], e)
    assert payments.handle_event(c, "payment.captured", p["id"], "payment.captured") == "duplicate"
    assert ledger.balances(c)["merchant_revenue"] == -5000 and not ledger.check_invariants(c)

def test_out_of_order_policies():
    for policy, final in (("park", "captured"), ("reject", "authorized")):
        c = connect()
        p, _ = payments.create_payment(c, "o", 100, "k")
        payments.handle_event(c, "e1", p["id"], "payment.captured", policy=policy)
        payments.handle_event(c, "e2", p["id"], "payment.authorized", policy=policy)
        assert payments.get(c, p["id"])["state"] == final

def test_unbalanced_rejected():
    with pytest.raises(ValueError):
        ledger.post(connect(), "x", [("a", 10, 0), ("b", 0, 9)])

def test_simulation_keeps_invariants_and_park_beats_reject():
    r = sim.compare(800)
    assert r["park"]["invariant_violations"] == [] and r["reject"]["invariant_violations"] == []
    assert r["park"]["state_accuracy_before"] > r["reject"]["state_accuracy_before"]
    assert r["park"]["matching"]["precision"] > 0.95

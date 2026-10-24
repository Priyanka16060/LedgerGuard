"""Payment state machine, idempotent creation, and webhook handling with two out-of-order policies."""
import sqlite3, time, uuid
from . import ledger

RANK = {"created": 0, "authorized": 1, "captured": 2, "refunded": 3}
LEGAL = {"created": {"authorized", "failed"}, "authorized": {"captured", "failed"},
         "captured": {"refunded"}, "failed": set(), "refunded": set()}
EVENT_TARGET = {"payment.authorized": "authorized", "payment.captured": "captured",
                "payment.failed": "failed", "payment.refunded": "refunded"}

def get(conn, pid):
    r = conn.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None

def create_payment(conn, order_id, amount, idem_key, now=None):
    """Same idempotency key always returns the same payment. Returns (payment, was_created)."""
    row = conn.execute("SELECT * FROM payments WHERE idem_key=?", (idem_key,)).fetchone()
    if row:
        return dict(row), False
    pid = "pay_" + uuid.uuid4().hex[:12]
    try:
        conn.execute("INSERT INTO payments(id,order_id,amount,idem_key,created_at) VALUES(?,?,?,?,?)",
                     (pid, order_id, amount, idem_key, now if now is not None else time.time()))
        conn.commit()
    except sqlite3.IntegrityError:  # lost a race on the unique key
        return dict(conn.execute("SELECT * FROM payments WHERE idem_key=?", (idem_key,)).fetchone()), False
    return get(conn, pid), True

def _apply(conn, pid, target):
    p = get(conn, pid)
    conn.execute("UPDATE payments SET state=? WHERE id=?", (target, pid))
    amt = p["amount"]
    if target == "captured":
        ledger.post(conn, f"cap:{pid}", [("gateway_receivable", amt, 0), ("merchant_revenue", 0, amt)], pid)
    elif target == "refunded":
        ledger.post(conn, f"ref:{pid}", [("merchant_revenue", amt, 0), ("gateway_receivable", 0, amt)], pid)

def _drain(conn, pid):
    """Apply parked events whose predecessor has now arrived."""
    while True:
        state = get(conn, pid)["state"]
        rows = conn.execute("SELECT target FROM pending_events WHERE payment_id=?", (pid,)).fetchall()
        nxt = next((r["target"] for r in rows if r["target"] in LEGAL[state]), None)
        if not nxt:
            return
        _apply(conn, pid, nxt)
        conn.execute("DELETE FROM pending_events WHERE payment_id=? AND target=?", (pid, nxt))

def handle_event(conn, event_id, payment_id, etype, gateway_ref=None, policy="park"):
    """policy 'reject': illegal-ahead events are dropped. 'park': stored, applied when legal."""
    target = EVENT_TARGET.get(etype)
    if target is None:
        return "ignored"
    if conn.execute("INSERT OR IGNORE INTO webhook_events VALUES(?,?,?,?)",
                    (event_id, payment_id, etype, "")).rowcount == 0:
        return "duplicate"
    p = get(conn, payment_id)
    if p is None:
        outcome = "unknown_payment"
    else:
        if gateway_ref and not p["gateway_ref"]:
            conn.execute("UPDATE payments SET gateway_ref=? WHERE id=?", (gateway_ref, payment_id))
        state = p["state"]
        if target in LEGAL[state]:
            _apply(conn, payment_id, target)
            if policy == "park":
                _drain(conn, payment_id)
            outcome = "applied"
        elif (state in ("failed", "refunded") or target == state or target == "failed"
              or (target in RANK and RANK[target] <= RANK[state])):
            outcome = "stale"
        elif policy == "park":
            conn.execute("INSERT OR IGNORE INTO pending_events VALUES(?,?)", (payment_id, target))
            outcome = "parked"
        else:
            outcome = "rejected"
    conn.execute("UPDATE webhook_events SET outcome=? WHERE event_id=?", (outcome, event_id))
    conn.commit()
    return outcome

def force_capture(conn, pid):
    """Used by reconciliation when the gateway's settlement file proves the money moved."""
    if get(conn, pid)["state"] in ("created", "authorized"):
        _apply(conn, pid, "captured")
        conn.execute("DELETE FROM pending_events WHERE payment_id=?", (pid,))
        return True
    return False

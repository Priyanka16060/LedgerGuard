"""Append-only double-entry ledger. Amounts are integer paise. Entries are never updated."""
import sqlite3

def post(conn, txn_id, lines, payment_id=None):
    """lines: [(account, debit, credit)]. Returns False if txn_id was already posted (idempotent)."""
    if sum(l[1] for l in lines) != sum(l[2] for l in lines):
        raise ValueError("unbalanced transaction")
    try:
        conn.execute("INSERT INTO ledger_txn VALUES(?,?)", (txn_id, payment_id))
    except sqlite3.IntegrityError:
        return False
    conn.executemany("INSERT INTO ledger_entries(txn_id,account,debit,credit) VALUES(?,?,?,?)",
                     [(txn_id, a, d, c) for a, d, c in lines])
    return True

def balances(conn):
    rows = conn.execute("SELECT account, SUM(debit) d, SUM(credit) c FROM ledger_entries GROUP BY account")
    return {r["account"]: r["d"] - r["c"] for r in rows}

def check_invariants(conn):
    """Rules that must hold after ANY sequence of failures. Returns list of violations."""
    v = []
    d, c = conn.execute("SELECT COALESCE(SUM(debit),0), COALESCE(SUM(credit),0) FROM ledger_entries").fetchone()
    if d != c:
        v.append(f"ledger unbalanced: debits {d} != credits {c}")
    for r in conn.execute("""SELECT txn_id FROM ledger_entries GROUP BY txn_id
                             HAVING SUM(debit) != SUM(credit)"""):
        v.append(f"txn {r[0]} unbalanced")
    for r in conn.execute("""SELECT id FROM payments WHERE state IN ('captured','refunded')
            AND NOT EXISTS (SELECT 1 FROM ledger_txn WHERE txn_id='cap:'||payments.id)"""):
        v.append(f"payment {r[0]} captured but no ledger entry")
    for r in conn.execute("""SELECT id FROM payments WHERE state IN ('created','authorized','failed')
            AND EXISTS (SELECT 1 FROM ledger_txn WHERE txn_id='cap:'||payments.id)"""):
        v.append(f"payment {r[0]} has revenue booked but state is not captured")
    for r in conn.execute("""SELECT id FROM payments WHERE settled=1 AND state NOT IN ('captured','refunded')"""):
        v.append(f"payment {r[0]} settled but not captured")
    return v

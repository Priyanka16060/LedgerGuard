import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments(
  id TEXT PRIMARY KEY, order_id TEXT NOT NULL, amount INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'created', gateway_ref TEXT,
  idem_key TEXT UNIQUE NOT NULL, created_at REAL NOT NULL, settled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS webhook_events(
  event_id TEXT PRIMARY KEY, payment_id TEXT, type TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS pending_events(
  payment_id TEXT, target TEXT, PRIMARY KEY(payment_id, target));
CREATE TABLE IF NOT EXISTS ledger_txn(txn_id TEXT PRIMARY KEY, payment_id TEXT);
CREATE TABLE IF NOT EXISTS ledger_entries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  txn_id TEXT NOT NULL REFERENCES ledger_txn(txn_id),
  account TEXT NOT NULL, debit INTEGER NOT NULL DEFAULT 0, credit INTEGER NOT NULL DEFAULT 0,
  CHECK(debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0)));
"""

def connect(path=":memory:"):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

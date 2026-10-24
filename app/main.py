from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from . import payments, ledger, sim
from .db import connect

app = FastAPI(title="LedgerGuard")
conn = connect("ledgerguard.db")

class PaymentIn(BaseModel):
    order_id: str
    amount: int  # paise

class WebhookIn(BaseModel):
    event_id: str
    payment_id: str
    type: str
    gateway_ref: str | None = None

@app.post("/payments")
def create(body: PaymentIn, idempotency_key: str = Header(...)):
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    p, created = payments.create_payment(conn, body.order_id, body.amount, idempotency_key)
    return {"payment": p, "created": created}

@app.post("/webhooks")
def webhook(body: WebhookIn, policy: str = "park"):
    return {"outcome": payments.handle_event(conn, body.event_id, body.payment_id, body.type, body.gateway_ref, policy)}

@app.get("/ledger/balances")
def balances():
    return ledger.balances(conn)

@app.get("/invariants")
def invariants():
    return {"violations": ledger.check_invariants(conn)}

@app.get("/api/simulate")
def simulate(n: int = 2000, seed: int = 7):
    return sim.compare(min(n, 10000), seed)

@app.get("/")
def ui():
    return FileResponse(Path(__file__).parent / "static" / "index.html")

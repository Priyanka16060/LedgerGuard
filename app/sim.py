"""Chaos simulator. Generates payments, delivers webhooks with duplicates/drops/reordering, builds a
gateway settlement file and bank credits with known ground truth, then measures the reconciler."""
import random
from .db import connect
from . import payments, ledger, reconcile

POPULAR = [29900, 49900, 99900, 149900, 199900]

def run(n=2000, seed=7, policy="park", drop=0.04, dup=0.10, swap=0.12,
        min_margin=0.35, slow_tail=0.0, learn_window=True):
    rng = random.Random(seed)
    conn = connect()
    truth, out = {}, {"duplicate_creates_blocked": 0, "webhooks": {}}
    t = 0.0
    for i in range(n):
        t += rng.expovariate(1 / 20)
        amount = rng.choice(POPULAR) if rng.random() < 0.6 else rng.randrange(10000, 300000, 100)
        p, _ = payments.create_payment(conn, f"ord_{i}", amount, f"idem_{i}", now=t)
        if rng.random() < 0.05:
            _, new = payments.create_payment(conn, f"ord_{i}", amount, f"idem_{i}", now=t)
            out["duplicate_creates_blocked"] += (not new)
        truth[p["id"]] = "captured" if rng.random() < 0.93 else "failed"
        evs = ["payment.failed"] if truth[p["id"]] == "failed" else ["payment.authorized", "payment.captured"]
        if len(evs) == 2 and rng.random() < swap:
            evs.reverse()
        for e in evs:
            if rng.random() < drop:
                out["webhooks"]["dropped"] = out["webhooks"].get("dropped", 0) + 1
                continue
            for _ in range(2 if rng.random() < dup else 1):
                r = payments.handle_event(conn, f"ev_{p['id']}_{e}", p["id"], e, "gw_" + p["id"][4:], policy)
                out["webhooks"][r] = out["webhooks"].get(r, 0) + 1

    def acc():
        rows = conn.execute("SELECT id,state FROM payments").fetchall()
        return round(sum(r["state"] == truth[r["id"]] for r in rows) / len(rows), 4)
    out["state_accuracy_before"] = acc()

    lines, true_map = [], {}
    for r in conn.execute("SELECT id,amount,created_at FROM payments").fetchall():
        if truth[r["id"]] != "captured":
            continue
        x = rng.random()
        ref = None if x < 0.08 else ("GW-" + r["id"][4:].upper() if x < 0.12 else "gw_" + r["id"][4:])
        lid = "ln_" + r["id"][4:]
        delay = rng.uniform(2, 45)
        if slow_tail and rng.random() < slow_tail:  # occasional slow settlement (long tail)
            delay = rng.uniform(45, 300)
        lines.append({"line_id": lid, "ref": ref, "gross": r["amount"], "fee": round(r["amount"] * 0.02),
                      "captured_at": r["created_at"] + delay})
        true_map[lid] = r["id"]
    lines.sort(key=lambda l: l["captured_at"])
    line_map = {l["line_id"]: l for l in lines}

    pays = [dict(r) for r in conn.execute(
        "SELECT id,amount,gateway_ref,created_at FROM payments WHERE state IN ('created','authorized','captured')")]
    matches, un_l, un_p = reconcile.match_lines(pays, lines, min_margin=min_margin, learn_window=learn_window)
    tiers = {}
    for m in matches:
        d = tiers.setdefault(m.tier if m.auto else "review", {"count": 0, "correct": 0})
        d["count"] += 1
        d["correct"] += (true_map[m.line_id] == m.payment_id)
    auto = [m for m in matches if m.auto]
    ok = sum(true_map[m.line_id] == m.payment_id for m in auto)

    out["matching"] = {"lines": len(lines), "auto_matched": len(auto), "auto_correct": ok,
                       "precision": round(ok / max(len(auto), 1), 4), "recall": round(ok / len(lines), 4),
                       "sent_to_review": len(matches) - len(auto), "unmatched_lines": len(un_l), "tiers": tiers}
    out["resolution"] = reconcile.resolve(conn, matches, line_map)
    out["state_accuracy_after"] = acc()

    cuts, credits = [0], []
    for b in range(50, len(lines), 50):
        cuts.append(b - (1 if rng.random() < 0.15 else 0))
    cuts.append(len(lines))
    true_groups = {}
    for k in range(len(cuts) - 1):
        seg = lines[cuts[k]:cuts[k + 1]]
        credits.append({"id": f"bank_{k}", "amount": sum(l["gross"] - l["fee"] for l in seg)})
        true_groups[f"bank_{k}"] = [l["line_id"] for l in seg]
    got = reconcile.group_credits(lines, credits)
    out["bank_credits"] = {"total": len(credits), "matched_exact": sum(got[c] == true_groups[c] for c in got)}
    out["invariant_violations"] = ledger.check_invariants(conn)
    out["policy"], out["payments"] = policy, n
    out["ledger_balances"] = ledger.balances(conn)
    return out

def compare(n=2000, seed=7):
    return {p: run(n, seed, p) for p in ("reject", "park")}

if __name__ == "__main__":
    import json
    print(json.dumps(compare(), indent=2))
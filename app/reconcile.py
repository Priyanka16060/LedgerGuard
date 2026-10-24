"""Reconciliation: match gateway settlement lines to our payments, then bank credits to line groups.
Matching is tiered: exact ref -> unique rule -> scored one-to-one assignment with an ambiguity guard."""
import math
from dataclasses import dataclass
from . import ledger, payments

@dataclass
class Match:
    line_id: str
    payment_id: str
    tier: str
    confidence: float
    auto: bool = True

def _score(dt, scale=60.0):
    return math.exp(-dt / scale)

def match_lines(pays, lines, tight=120.0, wide=600.0, min_margin=0.35, learn_window=True):
    matches, used_p, used_l = [], set(), set()
    delays = []
    # Tier 1: exact gateway reference + amount
    by_ref = {p["gateway_ref"]: p for p in pays if p["gateway_ref"]}
    for l in lines:
        p = by_ref.get(l["ref"]) if l["ref"] else None
        if p and p["id"] not in used_p and p["amount"] == l["gross"]:
            matches.append(Match(l["line_id"], p["id"], "exact", 1.0))
            used_p.add(p["id"]); used_l.add(l["line_id"])
            delays.append(l["captured_at"] - p["created_at"])
    # Candidate pairs for the rest: same amount, payment created before capture, inside a wide window
    rest_l = [l for l in lines if l["line_id"] not in used_l]
    rest_p = [p for p in pays if p["id"] not in used_p]
    if learn_window and len(delays) >= 50:
        delays.sort()
        lo = delays[int(0.005 * len(delays))] - 2.0
        hi = delays[int(0.995 * len(delays)) - 1] + 2.0
    else:
        lo, hi = 0.0, wide  
    by_l, by_p = {}, {}
    for l in rest_l:
        for p in rest_p:
            dt = l["captured_at"] - p["created_at"]
            if p["amount"] == l["gross"] and lo <= dt <= hi:
                s = _score(dt)
                by_l.setdefault(l["line_id"], []).append((s, p["id"], dt))
                by_p.setdefault(p["id"], []).append((s, l["line_id"], dt))

    def margin(lst):
        ss = sorted((x[0] for x in lst), reverse=True)
        return ss[0] - (ss[1] if len(ss) > 1 else 0.0)

    pairs = sorted(((s, lid, pid, dt) for lid, c in by_l.items() for s, pid, dt in c), reverse=True)
    for s, lid, pid, dt in pairs:
        if lid in used_l or pid in used_p:
            continue
        conf = min(margin(by_l[lid]), margin(by_p[pid]))
        unique = len(by_l[lid]) == 1 and len(by_p[pid]) == 1
        tier = "rule" if (unique and dt <= tight) else "scored"
        matches.append(Match(lid, pid, tier, round(conf, 3), auto=conf >= min_margin))
        used_l.add(lid); used_p.add(pid)
    un_l = [l["line_id"] for l in lines if l["line_id"] not in used_l]
    un_p = [p["id"] for p in pays if p["id"] not in used_p]
    return matches, un_l, un_p

def group_credits(lines, credits, max_skip=3):
    """Many-to-one: one bank credit = net of a contiguous run of settlement lines (unknown batch id).
    Prefix-sum scan; tolerates a few skipped lines and one-line carry-over between batches."""
    lines = sorted(lines, key=lambda l: l["captured_at"])
    i, out = 0, {}
    for c in credits:
        found = None
        for start in range(i, min(i + max_skip + 1, len(lines))):
            s = 0
            for j in range(start, len(lines)):
                s += lines[j]["gross"] - lines[j]["fee"]
                if s == c["amount"]:
                    found = (start, j); break
                if s > c["amount"]:
                    break
            if found:
                break
        if found:
            out[c["id"]] = [l["line_id"] for l in lines[found[0]:found[1] + 1]]
            i = found[1] + 1
        else:
            out[c["id"]] = None
    return out

def resolve(conn, matches, line_map):
    """Auto-resolve safe matches: gateway proof => capture + settlement postings. Others go to review."""
    fixed = settled = 0
    for m in matches:
        if not m.auto:
            continue
        p, l = payments.get(conn, m.payment_id), line_map[m.line_id]
        if p["state"] == "failed":
            m.auto = False  # gateway says paid but we think failed: a human decides
            continue
        if payments.force_capture(conn, m.payment_id):
            fixed += 1
        if ledger.post(conn, f"set:{m.line_id}", [
                ("bank", l["gross"] - l["fee"], 0), ("gateway_fees", l["fee"], 0),
                ("gateway_receivable", 0, l["gross"])], m.payment_id):
            settled += 1
        conn.execute("UPDATE payments SET settled=1 WHERE id=?", (m.payment_id,))
    conn.commit()
    return {"auto_fixed_states": fixed, "settled": settled}

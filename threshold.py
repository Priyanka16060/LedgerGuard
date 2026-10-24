from app import sim

margins = [ 0.35]
seeds = [41, 51, 61, 71, 81]

print("margin | precision | recall | review/run | wrong matches (total)")
for m in margins:
    P = R = rev = wrong = 0
    for s in seeds:
        r = sim.run(seed=s, min_margin=m)["matching"]
        P += r["precision"]
        R += r["recall"]
        rev += r["sent_to_review"]
        wrong += r["auto_matched"] - r["auto_correct"]
    k = len(seeds)
    print(f"{m:.2f}   | {P/k:.4f}    | {R/k:.4f} | {rev/k:.1f}       | {wrong}")
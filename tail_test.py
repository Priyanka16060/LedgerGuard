from app import sim

seeds = [3, 7, 11, 21, 31]
print("slow_tail | window | wrong matches | reviews/run")
for tail in (0.0, 0.05):
    for lw in (False, True):
        wrong = rev = 0
        for s in seeds:
            r = sim.run(seed=s, min_margin=0.35, slow_tail=tail, learn_window=lw)["matching"]
            wrong += r["auto_matched"] - r["auto_correct"]
            rev += r["sent_to_review"]
        print(f"{tail:<9} | {'on ' if lw else 'off'}    | {wrong:<13} | {rev/len(seeds):.1f}")
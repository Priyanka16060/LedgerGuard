## My contribution

The base system (double-entry ledger, idempotency keys, webhook state machine) uses established techniques.
My own work is on the **settlement matcher**: deciding when it is safe to auto-match a gateway
settlement line to a payment, and measuring that decision. I did this in three experiments, all run against
simulated data where the correct answer is known.

### 1. Choosing the confidence threshold
The matcher only auto-applies a match if its score beats the runner-up by at least `min_margin`.
Otherwise the case goes to human review. I swept the margin over 5 seeds (3, 7, 11, 21, 31):

| Margin | Wrong auto-matches | Reviews per run | Precision | Recall |
|---|---|---|---|---|
| 0.05 | 18 | 1.6 | 99.80% | 99.72% |
| 0.15 | 11 | 3.2 | 99.88% | 99.71% |
| 0.25 | 4 | 6.0 | 99.96% | 99.63% |
| 0.35 | 1 | 9.8 | 99.99% | 99.46% |
| 0.50 | 0 | 29.4 | 100.00% | 98.42% |

Going from 0.35 to 0.50 removes one more error but adds about 20 reviews per run, so I treated 0.35 as the
knee of the curve. On 5 unseen seeds (41, 51, 61, 71, 81) both 0.25 and 0.35 gave 0 wrong matches.
I chose **0.35**, because a wrong money movement costs far more than a review. If review capacity
were the limit, 0.25 would be the alternative.

(Recall counts review items as not matched, but a human resolves those. So lower recall means more
manual work, not more wrong results.)

### 2. Finding the failure cases and adding a learned delay window
On seed 21, six auto-matches were wrong. All were in the scored tier, with confidence just above the
threshold (0.165 to 0.302). Some picked a payment created moments before the line, when the line really
belonged to an older one. Some picked payments whose delay was impossible for this gateway.
I added a **delay window learned from the exact-reference matches** (0.5th to 99.5th percentile, plus a
2 second pad), and used it to drop impossible candidates.

| Margin | Wrong matches before / after | Reviews per run before / after |
|---|---|---|
| 0.15 | 11 / 5 | 3.2 / 2.4 |
| 0.25 | 4 / 4 | 6.0 / 4.0 |
| 0.35 | 1 / 1 | 9.8 / 5.0 |

At margin 0.35 the window left the error count unchanged and cut manual reviews by about half.
With the window on, the final matcher again gave 0 wrong matches on the unseen seeds.

### 3. Testing a weakness: slow settlements
The simulator's delays were clean (2 to 45 seconds). To test a harder case I made 5% of settlements slow
(45 to 300 seconds). Margin 0.35, 5 seeds:

| Slow tail | Window | Wrong matches | Reviews per run |
|---|---|---|---|
| 0% | off | 1 | 9.8 |
| 0% | on | 1 | 5.0 |
| 5% | off | 1 | 22.0 |
| 5% | on | 1 | 20.6 |

With a long tail the learned window widens to cover the slow cases, so its benefit shrinks to about 6%.
Accuracy held, though: the system sent about 20 payments per run (roughly 1%) to review instead of guessing.
It becomes slower, not wrong.

## Limits
- **Simulated data.** All results come from my own simulator, which also generated the test data. Real
  gateway delays, amounts and failure patterns will be messier, so the numbers show the method works, not
  how it would perform in production.
- **Small sample.** Each result uses 5 seeds, and errors are rare (0 to 18 in total per setting), so small
  differences are not statistically meaningful. I claim that the window reduces review workload, not that it
  improves accuracy.
- **Long tails.** The learned window loses most of its value when settlement delays have a long tail
  (see experiment 3). A better design would score candidates by how likely their delay is under the learned
  distribution, instead of using a hard cutoff. I have not built this.
- **Cause of some errors not confirmed.** I believe some wrong matches come from the one-to-one assignment
  step (a line forced onto its second choice after another line took its payment), but I did not verify this.
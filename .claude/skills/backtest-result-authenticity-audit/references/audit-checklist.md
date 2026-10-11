# Backtest authenticity audit checklist

Run every step in order. Any failure is disqualifying: stop, fix the root cause, then restart the audit from the beginning, since a fix in one area can sometimes interact with another. Record the actual result of every step, not just pass/fail.

## Step 1: Lookahead bias (see lookahead-bias-detection-methodology)

- [ ] **Truncation test**: rerun the backtest with data cut off at 2-3 different dates spread through the backtest period. Pass criterion: every decision made before each cutoff is byte-for-byte identical between the truncated run and the full-history run. Record: which dates were tested, and whether any decision differed.
- [ ] **Future-corruption test**: replace a block of future data (a date range well after the period being checked) with randomized garbage values, rerun, and confirm decisions before that range are unchanged. Pass criterion: zero difference in any decision before the corrupted range. Record: which date range was corrupted and the diff result.
- [ ] **Feature/signal code audit**: for every feature or signal, confirm every data point it reads has a timestamp at or before the decision timestamp. Pass criterion: no feature reads data timestamped after its own decision point. Record: any feature flagged and how it was resolved.
- [ ] **Data merge/join audit**: for every point where separate data sources are combined, confirm the actual availability timestamp (not the nominal date field) was used for alignment. Pass criterion: every merge verified against real availability timing. Record: which merges were checked.

## Step 2: Fill feasibility (see fill-feasibility-and-impossible-fill-detection)

- [ ] **Volume feasibility scan**: check every simulated fill's size against the real historical volume of its fill bar. Pass criterion: no fill represents an implausible fraction of that bar's actual volume (define the threshold explicitly for the instrument's typical liquidity, and record what threshold was used). Record: fraction of trades flagged, and the resolution for each.
- [ ] **Intrabar range check**: for every stop/limit fill, confirm the bar's actual high/low range genuinely reached the order's trigger price. Pass criterion: no fill assumed at a price the bar's real range never touched. Record: number of fills checked and any flagged.
- [ ] **Low-liquidity/gap/halt bar review**: identify every fill that occurred on a zero-volume, gapped, or halted bar. Pass criterion: each such fill has an explicit, deliberately more conservative fill assumption or has been flagged for manual review, not filled through with the same logic as a normal liquid bar. Record: list of flagged bars and their resolution.
- [ ] **Spread consistency check** (where quote data exists): confirm no fill crosses inside the historical bid-ask spread in an unrealistic direction. Pass criterion: all fills respect real historical spread. Record: whether quote data was available, and results if so.

## Step 3: Intrabar precision (see order-book-and-intrabar-price-path-modeling), where finer-grained data is available

- [ ] **Tick-level path reconstruction**: where tick data exists, confirm fill timing/probability for limit/stop orders is derived from the actual trade sequence, not just bar-level OHLC. Record: whether tick data was available and used.
- [ ] **Order-book depth check**: where Level 2 data exists, confirm fill sizes are checked against real available depth at the fill moment. Record: whether order-book data was available and used.
- [ ] **Explicit limitation statement**: where only OHLC data is available, this is documented explicitly as a known source of fill-assumption uncertainty, factored into the Monte Carlo resampling and stress-testing steps elsewhere in this repo. Record: the limitation statement itself.

## Step 4: Real-fill reconciliation (see backtest-vs-broker-fill-reconciliation), where real fill history exists

- [ ] **Direct comparison**: the same historical orders/timestamps have been run through both the backtest's fill logic and compared against real broker/execution fills for the same instrument. Record: sample size and comparison method.
- [ ] **Bias distribution check**: the full distribution of simulated-vs-real fill differences has been examined for systematic directional bias, not just an average. Record: the measured distribution and any bias found.
- [ ] **Conditional breakdown**: reconciliation results are segmented by order type, size, and market condition. Record: results by segment.
- [ ] **Feedback applied**: any systematic gap found has been fed back into the fill model and cost assumptions, with the strategy re-validated under corrected assumptions. Record: what was changed and the re-validation result.

## Sign-off

- [ ] All steps above are complete, with every finding recorded, not just a final pass/fail summary.
- [ ] Any failure encountered during the audit was resolved at its root cause, and the full audit was restarted from Step 1 after the fix, not resumed from the point of failure.
- [ ] The completed audit record is stored as part of this strategy version's research log entry (see strategy-research-log-and-versioning), tied to the specific code/config/data version it was run against.

---
name: overfitting-and-robustness-checks
description: 'Use this skill whenever building, backtesting, tuning, or reviewing a trading strategy or algorithm, and especially whenever a backtest reports metrics that look strong. Also use it when a user asks to "optimize my strategy," "backtest this," "improve my Sharpe," or shares backtest results and asks whether they look good. This skill exists because a model has no built-in incentive to say a great-looking backtest is fake, and most retail algos that blow up live were never actually tested for robustness, only tuned until the report looked good on the exact data used to tune them.'
---

# Overfitting and Robustness Checks

## Why this matters

A backtest is not evidence a strategy works. It is evidence that some set of rules, on some specific slice of historical data, produced some specific sequence of trades. Whether that generalizes to markets the strategy has never seen is a completely separate question, and it's the one that actually matters, because live capital only ever trades on data the backtest never saw.

Left unchecked, an agent (or a person) iterating on a strategy will keep adjusting parameters until the backtest looks good, then stop. That process is curve-fitting by construction: it selects for whichever version of the strategy happened to match the noise in that specific historical sample, not for a real, persistent edge. The backtest will look better and better every iteration while the odds it reflects anything real get worse and worse. This is the single most common way retail algo strategies fail: not because the market was unpredictable, but because the "edge" being deployed live was never there in the first place, only in the fitting process.

## Do this

### Split data before touching parameters, not after

Set aside an out-of-sample period before any optimization begins, and never let it influence a single parameter choice. A common split is 60-70% in-sample (design and tuning) and 30-40% out-of-sample (held out completely), split chronologically, never randomly shuffled, since a time series strategy tested on shuffled data is being tested on a different, easier problem than the one it will actually face live. If the strategy's edge doesn't survive on the out-of-sample slice with broadly similar performance to in-sample, the strategy doesn't have an edge; it has a fit.

### Run walk-forward validation, not just one train/test split

A single out-of-sample period can itself be lucky or unlucky. Walk-forward analysis re-optimizes on a rolling or expanding window and tests on the period immediately after it, repeated across the whole dataset, so the strategy gets evaluated out-of-sample many times over different market conditions instead of once. Track performance across each successive out-of-sample segment specifically looking for decay: a strategy that performs well in segment 1's out-of-sample window and progressively worse in segments 2 through 5 is telling you the "edge" doesn't survive contact with data it wasn't tuned on, which is the whole point of running this in the first place.

### Treat suspiciously good metrics as a bug report against yourself, not a win

Real, sustained trading edges are rare and hard-won; when a backtest reports numbers far outside what real strategies achieve, the correct first reaction is "what's wrong with my backtest," not "I found something great." See [references/robustness-thresholds.md](references/robustness-thresholds.md) for specific numeric ranges, but as a starting orientation: a Sharpe ratio holding above roughly 3.5 out of sample, a MAR ratio (CAGR divided by max drawdown) above roughly 6-8, or an equity curve whose shape is close to a straight line (formally: a very high R² when fit against a straight line, or drawdown periods that are unnaturally short and shallow relative to the total backtest length) are all signals worth investigating before they're signals worth celebrating. Investigate by checking for lookahead bias, checking whether the result survives cost stress-testing, and checking whether it survives on a genuinely held-out period, before assuming the number is real.

### Match parameter count to the amount of independent data available

Every tunable parameter is a degree of freedom the optimizer can use to fit noise instead of signal. A strategy with ten tunable parameters validated on forty trades has enormously more freedom to fit than the data can actually support; there is no universal exact ratio, but a strategy should be validated on a number of independent trades that is at minimum in the dozens per parameter, and ideally far more for anything with real behavioral complexity (multiple entry conditions, multiple exit conditions, regime filters, etc). If the parameter count can't be justified against the trade count, the fix is fewer parameters, not more data massaging.

### Keep a log of every variant tried, not just the winner that shipped

If twenty strategy variants were tested and one looked good, that one variant's backtest needs to be judged in light of having been selected out of twenty attempts, not evaluated as if it were the only thing tried. This is the same statistical issue as multiple-comparisons in any other field: the more variations tested, the more likely one clears an impressive-looking bar purely by chance, and the more skeptically that winner needs to be treated. Log every real variant attempted (not just parameter tweaks within one structure, but genuinely different rule sets) so the final result can be judged against how much search actually happened to find it.

### Model realistic transaction costs, then stress-test them upward

Commissions, slippage, and bid-ask spread are not rounding errors, especially for strategies that trade frequently or trade less liquid instruments. Model costs that reflect the actual instrument and venue (spread and slippage assumptions for a liquid futures contract are very different from a thin small-cap or an altcoin), then re-run the backtest with costs deliberately increased (for example 1.5x and 2x the base assumption) to see whether the edge survives. A strategy whose profitability disappears under a modest cost increase was living on an assumption, not an edge.

### Actively check for lookahead and survivorship bias in the data pipeline itself

Lookahead bias is often a plumbing bug, not a strategy design flaw: using a bar's closing price to generate a signal that then trades on that same bar, using restated fundamental or adjusted-price data that was not actually knowable at the historical timestamp being simulated, or misaligned timestamps between two data feeds that let information leak backward in time. Survivorship bias shows up specifically in equity backtests that only include symbols that are still listed today, silently excluding the delisted, bankrupted, and merged-away companies that a live strategy in the past would have actually held. Both biases push backtest results in the same direction: too good. Check the data pipeline for both explicitly rather than assuming a data provider or backtesting library handles it correctly by default; see [`market-data-sourcing`](../market-data-sourcing/SKILL.md) for provider-specific notes on which sources are and aren't survivorship-bias-free.

### Resample the trade sequence instead of trusting one lucky (or unlucky) ordering

A backtest produces one specific sequence of wins and losses. Bootstrap resampling (shuffling or resampling the trade returns with replacement, many times, to build a distribution of possible equity curves) shows how much of the result depended on the specific order trades happened to occur in, versus how much is robust across many plausible orderings. A strategy whose Monte Carlo distribution of outcomes includes a wide range of max drawdowns, including some materially worse than what the single historical backtest showed, needs to be sized and risked for that wider distribution, not for the one path that happened to occur historically.

### Test across more than one market regime before trusting the result

A backtest run only over a multi-year bull market, or only over a specific volatility regime, tells you how the strategy did in that regime, not how it will do generally. Deliberately test across genuinely different conditions the strategy is likely to eventually face: trending vs. choppy periods, high-volatility vs. low-volatility periods, and if the history is available, more than one full market cycle. A strategy that only works in one regime isn't necessarily worthless, but it needs to be deployed and sized with that limitation explicitly acknowledged, not discovered live.

### Forward-test on paper before it trades real capital

A held-out historical period is still historical; a live paper-trading period is the first genuinely prospective test the strategy gets, generating signals in real time on data that didn't exist when the strategy was built. Require a forward paper-trading period, ideally long enough to include a reasonable sample of trades for the strategy's frequency, and compare its live-forward performance against what the backtest predicted before committing real capital. A meaningful gap between paper performance and backtest expectations is exactly the kind of drift that turns an apparently-solid backtest into a real loss once money is actually on the line.

## Never do this

- Never optimize parameters on the full dataset and then report that same full-dataset performance as though it were an out-of-sample result.
- Never treat a single train/test split as sufficient; always prefer walk-forward validation across multiple out-of-sample windows.
- Never accept a suspiciously strong Sharpe, MAR ratio, or an unnaturally smooth equity curve at face value without investigating for lookahead bias, unrealistic costs, or an overly narrow test period first.
- Never let the number of tunable parameters grow without checking it against how many independent trades the backtest actually produced.
- Never report only the winning variant's backtest without disclosing how many variants were tried to find it.
- Never backtest with zero or token transaction costs, and never skip stress-testing costs upward to check sensitivity.
- Never assume a data provider or library already handles lookahead and survivorship bias correctly; check the actual pipeline.
- Never size a live strategy off the single historical equity curve's max drawdown without also checking a resampled distribution of plausible drawdowns.
- Never deploy real capital straight from a backtest without a live paper-trading forward-test period first.

## Verification checklist

- [ ] Data was split chronologically into in-sample and out-of-sample before any parameter tuning began, and the out-of-sample slice was never used to influence a parameter choice
- [ ] Walk-forward validation was run across multiple rolling or expanding windows, and out-of-sample performance was checked for decay across successive segments, not just measured once
- [ ] Sharpe ratio, MAR ratio, and equity curve smoothness were checked against the red-flag ranges in [references/robustness-thresholds.md](references/robustness-thresholds.md), and any suspiciously strong result was investigated for a cause before being treated as good news
- [ ] The number of tunable parameters was checked against the number of independent trades the backtest actually produced
- [ ] Every real strategy variant tried was logged, not only the one that shipped, so the final result can be judged against how much search it took to find
- [ ] Transaction costs, slippage, and spread were modeled realistically for the actual instrument and venue, and the result was stress-tested against increased costs
- [ ] The data pipeline was checked explicitly for lookahead bias (signal and execution timing, data restatement, feed timestamp alignment) and, for equities, survivorship bias
- [ ] The trade sequence was resampled (bootstrap or Monte Carlo) to check how much of the result depends on the specific historical ordering of trades
- [ ] The strategy was tested across more than one market regime, not only the most favorable period available
- [ ] A live paper-trading forward-test period ran before any real capital was committed, and its results were compared against backtest expectations

See [references/robustness-thresholds.md](references/robustness-thresholds.md) for specific numeric ranges on Sharpe ratio, MAR ratio, equity curve smoothness, and what each red flag typically indicates when it shows up.

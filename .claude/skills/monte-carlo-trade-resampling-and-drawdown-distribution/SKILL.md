---
name: monte-carlo-trade-resampling-and-drawdown-distribution
description: 'Use this skill on every strategy backtest before its drawdown or return statistics are trusted for sizing or risk decisions, and whenever a user reports a single backtest''s max drawdown as if it were the worst case to plan around. Also use it when a user asks to "run a Monte Carlo" on a strategy or wants to know how much worse things could realistically have gone. This skill exists because a backtest produces exactly one historical ordering of trades, and that one ordering can be meaningfully luckier or unluckier than what the strategy''s actual return distribution implies, in ways that matter enormously for sizing and risk limits.'
---

# Monte Carlo Trade Resampling and Drawdown Distribution

## Why this matters

A backtest's reported max drawdown is the max drawdown of one specific sequence of trades, in the specific order they happened to occur historically. If the exact same set of trades had occurred in a different order, purely by chance, the drawdown could easily have been meaningfully worse (or better). Sizing a strategy, or deciding it's safe to trade, based on the single historical drawdown figure is implicitly assuming that historical ordering was representative of what could happen, when it's really just one draw from a much wider range of possible outcomes.

## Do this

### Run a minimum of 2000 resampled trade sequences before trusting any drawdown or return statistic for sizing decisions

Resample the strategy's historical trade returns with replacement to build a new synthetic equity curve, repeat this a minimum of 2000 times, and compute the resulting distribution of outcomes (max drawdown, CAGR, time-to-recovery, and any other statistic being used for sizing or risk decisions). Two thousand runs is the floor, not a target to hit and stop at; the point is to have enough resampled paths that the tails of the distribution (the 1st and 99th percentiles, not just the median) are estimated with reasonable stability rather than being noisy themselves. Report the 5th, 25th, 50th, 75th, and 95th percentile outcomes, not just the mean or median, since sizing and risk decisions should be made against the pessimistic end of that distribution, not the central tendency.

### Use block bootstrap resampling in addition to simple resampling, to preserve autocorrelation

Simple resampling with replacement treats each trade's return as independent of the others, which understates risk for any strategy where returns are actually autocorrelated (losing trades tend to cluster, for instance, because a losing regime affects consecutive trades similarly). Block bootstrap resampling draws contiguous blocks of consecutive trades rather than individual trades, preserving whatever autocorrelation structure exists in the real data. Run both simple and block bootstrap resampling and compare the resulting distributions; a large difference between them is itself informative about how much the strategy's risk is understated by treating trades as independent.

### Check where the single historical backtest's actual result falls within the resampled distribution

If the historical backtest's max drawdown sits near the 5th percentile (a relatively favorable outcome) of the resampled distribution rather than near the median, that's a direct, quantified way of seeing that the single historical path was luckier than what the strategy's own return distribution implies is typical. This is a much more precise version of [overfitting-and-robustness-checks](../overfitting-and-robustness-checks/SKILL.md)'s "does this equity curve look too smooth" heuristic, and should be checked explicitly rather than eyeballing the equity curve shape alone.

### Size positions and set risk limits against the resampled distribution's pessimistic percentiles, not the single historical result

Position sizing and maximum-drawdown risk limits should be set with reference to a pessimistic percentile of the resampled distribution (the 90th or 95th percentile drawdown, for instance), not the single historical backtest's max drawdown, since the single historical figure is one sample from a wider range of what could plausibly happen, and betting the account's risk tolerance on that one sample being representative is itself a form of overconfidence in the backtest.

### Re-run the resampling whenever the strategy or its underlying trade data materially changes

A resampled distribution computed once and never revisited becomes stale as the strategy is modified or as more real trading history accumulates. Re-run the full resampling process (at minimum the 2000-run standard) whenever the strategy's rules change materially or whenever a meaningful amount of new trade history becomes available, rather than treating one resampling run as a permanent, one-time result.

## Never do this

- Never rely on a single historical backtest's max drawdown as the figure used for position sizing or risk limits without first checking where it falls in a resampled distribution.
- Never run fewer than 2000 resampled trade sequences when building the distribution used for sizing or risk decisions; smaller sample counts leave the tail percentiles too noisy to trust.
- Never use only simple (independent) resampling without also checking block bootstrap results, especially for strategies where consecutive trade returns are plausibly correlated.
- Never size a strategy against the median or mean of a resampled distribution instead of a pessimistic tail percentile; risk limits exist for the bad outcomes, not the typical ones.
- Never treat a resampling run from an earlier version of the strategy as still valid after the strategy's rules have materially changed.

## Verification checklist

- [ ] At least 2000 resampled trade sequences were generated before any drawdown or return statistic was used for sizing or risk decisions
- [ ] Both simple (independent) resampling and block bootstrap resampling were run and compared, not simple resampling alone
- [ ] The full percentile range (at minimum 5th/25th/50th/75th/95th) of the resampled distribution was computed and reported, not just a mean or median
- [ ] The single historical backtest's actual max drawdown was checked against where it falls within the resampled distribution, not assumed to be representative
- [ ] Position sizing and risk limits are set against a pessimistic percentile of the resampled distribution, not the single historical result
- [ ] The resampling was re-run after any material change to the strategy's rules or a meaningful accumulation of new trade history

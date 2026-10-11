---
name: statistical-significance-and-deflated-metrics
description: 'Use this skill whenever a strategy''s backtested Sharpe ratio or other performance metric is being used to decide whether the strategy has real edge, especially after multiple strategy variants, parameter sets, or feature combinations were tried to find the one being evaluated. Also use it when a user asks "is this Sharpe actually good" or "how do I know this isn''t just luck." This skill exists because a raw backtested Sharpe ratio, taken at face value, systematically overstates how likely a strategy is to have real edge whenever more than one variant was tried to find it, which is nearly always.'
---

# Statistical Significance and Deflated Metrics

## Why this matters

A Sharpe ratio computed on a backtest answers "how good did this specific strategy look on this specific data," not "how likely is it that this strategy has a real edge." Those are different questions, and the gap between them grows every time another variant, parameter set, or feature combination gets tried in the search for something that looks good. Trying twenty variants and reporting the best one's Sharpe as though it were the only thing tried is a straightforward form of selection bias, the same statistical issue as multiple comparisons in any other empirical field, and it inflates the apparent significance of the result by an amount that grows with how many things were actually tried.

## Do this

### Track the number of trials that went into finding the reported result

The deflated Sharpe ratio and related techniques need to know how many independent trials (distinct strategy variants, parameter combinations, or feature sets genuinely tried, not just minor numerical tweaks within one fixed structure) were run to find the one being reported. This depends directly on the research log discipline in [strategy-research-log-and-versioning](../strategy-research-log-and-versioning/SKILL.md): without an honest count of what was actually tried, no correction for multiple testing can be computed at all, and the reported Sharpe has to be treated as maximally suspect by default.

### Apply a deflated Sharpe ratio calculation rather than reporting the raw Sharpe alone

The deflated Sharpe ratio (Bailey and Lopez de Prado's formulation) adjusts the raw Sharpe for the number of independent trials, the length of the track record, and the skewness/kurtosis of the returns, producing an estimate of how likely the observed Sharpe is to reflect a real, non-zero edge rather than noise, given how much searching happened to find it. Compute and report this alongside the raw Sharpe, not instead of understanding the raw number, since the deflated figure is specifically the number that answers "is this real" rather than "does this look good."

### Estimate the probability of backtest overfitting (PBO), not just a point estimate of Sharpe

PBO methods (such as combinatorially splitting the backtest into multiple in-sample/out-of-sample partitions and checking how often the in-sample-best variant underperforms out-of-sample relative to the other variants tried) give a direct estimate of how likely it is that the specific variant selected as "best" was selected because it fit the in-sample noise best, rather than because it has genuinely better expected performance. A high estimated PBO is a direct, quantified version of the qualitative warning in [overfitting-and-robustness-checks](../overfitting-and-robustness-checks/SKILL.md) about suspiciously good in-sample results.

### Use combinatorial purged cross-validation for a more robust significance estimate than a single train/test split

A single train/test split, even a well-chosen one, gives one sample of out-of-sample performance. Combinatorial purged cross-validation partitions the data into multiple groups, tests many different train/test combinations built from those groups while purging data near the train/test boundary to avoid leakage from overlapping labels (relevant when any feature or label uses a lookback or lookahead window), and produces a distribution of out-of-sample performance estimates rather than a single number. That distribution is far more informative about how consistently the strategy performs out-of-sample than any single split can be.

### Treat statistical significance as necessary, not sufficient

A strategy that clears a significance bar (a high deflated Sharpe, a low estimated PBO) has cleared a meaningful hurdle that most overfit strategies won't clear, but it still needs everything else in this repo: a real hypothesis ([hypothesis-driven-strategy-design](../hypothesis-driven-strategy-design/SKILL.md)), realistic costs, and a live forward test before real capital is at risk. Statistical significance rules out one specific failure mode (this specific result being explainable by how much searching happened); it doesn't rule out lookahead bias, unrealistic costs, or the edge simply not persisting going forward.

## Never do this

- Never report a backtested Sharpe ratio or similar metric without disclosing how many variants were tried to find it; an undisclosed trial count makes the reported number impossible to properly evaluate.
- Never treat a raw, undeflated Sharpe ratio as sufficient evidence of a real edge once more than a handful of variants were tried.
- Never rely on a single train/test split's out-of-sample performance as a complete significance estimate when combinatorial methods that produce a full distribution are available and computationally feasible.
- Never treat a strong deflated Sharpe or low PBO estimate as sufficient on its own; it addresses selection bias specifically, not lookahead bias, cost realism, or forward persistence.
- Never compute cross-validation splits for a time series strategy without purging data near train/test boundaries when features or labels use lookback/lookahead windows; failing to purge reintroduces the leakage the split was meant to prevent.

## Verification checklist

- [ ] The number of genuinely distinct strategy variants, parameter sets, or feature combinations tried to find the reported result is tracked and disclosed, not lost
- [ ] A deflated Sharpe ratio (or equivalent trial-count-adjusted significance estimate) is computed and reported alongside the raw Sharpe
- [ ] An estimated probability of backtest overfitting has been computed via a combinatorial in-sample/out-of-sample partitioning method, not assumed
- [ ] Cross-validation splits are purged near train/test boundaries when any feature or label involves a lookback or lookahead window
- [ ] A statistically significant result is still being subjected to the rest of this repo's checks (hypothesis, cost realism, forward testing) rather than being treated as fully validated on its own

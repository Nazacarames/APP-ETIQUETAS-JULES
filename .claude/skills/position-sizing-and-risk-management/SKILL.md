---
name: position-sizing-and-risk-management
description: 'Use this skill whenever deciding how large a position or a strategy''s overall allocation should be, and whenever a user asks about leverage, Kelly criterion sizing, or how much capital to risk per trade. Also use it when reviewing a strategy that has good backtested edge metrics but no explicit sizing methodology, since a real edge sized wrong can still lose money or blow up an account. This skill exists because sizing decisions are where a strategy''s statistical edge actually meets real capital and real ruin risk, and getting the edge right while getting the sizing wrong is a completely avoidable way to fail.'
---

# Position Sizing and Risk Management

## Why this matters

A statistically real edge, validated through everything in [overfitting-and-robustness-checks](../overfitting-and-robustness-checks/SKILL.md) and [monte-carlo-trade-resampling-and-drawdown-distribution](../monte-carlo-trade-resampling-and-drawdown-distribution/SKILL.md), can still lose money or blow up an account if sized wrong. Position sizing is where a strategy's edge and its risk of ruin actually meet, and the two most common sizing failures pull in opposite directions: sizing too aggressively based on a backtested edge that doesn't hold up in the same way live, or a single unusually bad tail event happening earlier than the sizing accounted for; and sizing too conservatively, which wastes a real edge by extracting far less from it than it could safely support.

## Do this

### Use the resampled drawdown distribution, not the single historical backtest, to set sizing limits

Consistent with [monte-carlo-trade-resampling-and-drawdown-distribution](../monte-carlo-trade-resampling-and-drawdown-distribution/SKILL.md), size positions and set maximum-drawdown risk limits against a pessimistic percentile of the resampled distribution (the 90th or 95th percentile drawdown), not the single historical backtest's max drawdown. The single historical figure is one sample from a wider range of plausible outcomes, and sizing against it alone assumes that sample was representative of the worst case, which it usually wasn't.

### Understand the Kelly criterion's actual assumptions before using any fraction of it

The Kelly criterion computes the theoretically growth-optimal bet size given a known, fixed edge and variance, but it assumes those inputs are known exactly, which they never are in practice; real edge estimates from a backtest carry real uncertainty, and full Kelly sizing on an uncertain, possibly-overestimated edge is a well-known way to oversize dramatically. Using a fraction of Kelly (commonly a quarter to a half) is a common practical adjustment specifically because it reduces sensitivity to edge-estimation error, and any Kelly-based sizing needs to explicitly account for the fact that the input edge estimate itself has uncertainty, not just compute the formula against a backtested edge as though it were a known constant.

### Target volatility explicitly, and rescale position size as realized volatility changes

Sizing a position as a fixed dollar or fixed-percentage amount, without adjusting for the instrument's current volatility, means the position's actual risk contribution changes as volatility changes, often growing exactly when volatility (and often correlation and tail risk) is rising. Volatility targeting (sizing inversely to a rolling estimate of realized or implied volatility) keeps the position's risk contribution more stable through changing market conditions, and should be an explicit, deliberate sizing mechanism rather than an afterthought.

### Set explicit portfolio-level heat limits, not just per-position limits

A portfolio of multiple positions or strategies can have a small per-position risk limit on each individual position while still carrying a large aggregate risk if those positions are more correlated than assumed (see [portfolio-construction-and-correlation-checks](../portfolio-construction-and-correlation-checks/SKILL.md)). Set an explicit limit on total portfolio risk ("heat"), computed from the actual correlation structure of current positions, not just the sum of independently-set per-position limits, which can understate real aggregate risk when positions move together.

### Build explicit, rule-based de-risking triggers tied to drawdown, not discretionary in-the-moment decisions

Decide in advance, before a drawdown happens, what specific drawdown levels trigger specific position-size reductions, and implement that as a rule the system follows automatically, rather than relying on a discretionary decision to reduce risk made in the emotionally difficult moment when a real drawdown is actually happening. A rule decided calmly in advance is far more likely to actually get followed than a decision made under the stress of live losses.

### Distinguish sizing a single strategy from sizing an evolving portfolio of strategies over time

A strategy's appropriate size can change as more live evidence accumulates about whether its backtested edge is holding up; build an explicit process for scaling a strategy's allocation up or down based on its live track record relative to backtest expectations (see [capital-allocation-and-strategy-lifecycle](../capital-allocation-and-strategy-lifecycle/SKILL.md)), rather than sizing once at deployment and never revisiting it.

## Never do this

- Never size positions or set drawdown risk limits against a single historical backtest's max drawdown without first checking a resampled distribution of plausible outcomes.
- Never use full Kelly sizing against a backtested edge estimate as though that estimate were a known, certain constant; account explicitly for edge-estimation uncertainty, commonly via a fractional-Kelly approach.
- Never size a position as a fixed dollar or percentage amount without considering how the instrument's current volatility affects the position's actual risk contribution.
- Never rely on the sum of independently-set per-position risk limits as a substitute for an explicit, correlation-aware portfolio-level risk limit.
- Never leave de-risking decisions to be made discretionarily during an actual drawdown; decide the rules in advance.
- Never size a strategy once at deployment and leave that sizing static regardless of how its live performance compares to backtest expectations over time.

## Verification checklist

- [ ] Position sizing and drawdown risk limits are set against a pessimistic percentile of a resampled outcome distribution, not the single historical backtest's max drawdown
- [ ] Any Kelly-based sizing explicitly accounts for uncertainty in the underlying edge estimate, typically via a fractional-Kelly approach, rather than treating the backtested edge as a known constant
- [ ] Position sizes are adjusted for the instrument's current volatility (volatility targeting), not held as a fixed dollar or percentage amount regardless of changing conditions
- [ ] An explicit portfolio-level risk ("heat") limit exists, computed from the actual correlation structure of current positions, not just summed independently from per-position limits
- [ ] De-risking triggers tied to specific drawdown levels are decided and automated in advance, not left to discretionary in-the-moment decisions
- [ ] A strategy's sizing is revisited over time based on its live track record relative to backtest expectations, not set once and left static

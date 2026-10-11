---
name: momentum-and-trend-following-pitfalls
description: 'Use this skill when building, reviewing, or validating a momentum or trend-following strategy specifically, in addition to the general checks in overfitting-and-robustness-checks. Also use it when a user describes a strategy that trades based on price direction persisting, moving averages, breakouts, or similar trend-based signals. This skill exists because trend-following has specific, well-known failure modes (whipsaw in choppy markets, trailing-stop design tradeoffs, sizing that doesn''t account for its structurally lumpy return distribution) that a generic overfitting checklist doesn''t fully address on its own.'
---

# Momentum and Trend-Following Pitfalls

## Why this matters

Trend-following strategies have a genuinely different return distribution shape than most other strategy types: many small losses during range-bound, choppy conditions, punctuated by occasional large gains during real trends, per [edge-taxonomy-and-strategy-classification](../edge-taxonomy-and-strategy-classification/SKILL.md). That shape creates specific evaluation and design pitfalls, most importantly that a smooth-looking backtest is a red flag rather than a good sign for this category, and that naive whipsaw handling can silently be the difference between a strategy with real long-run edge and one that bleeds away in chop before ever capturing a real trend.

## Do this

### Expect and require real, extended losing streaks during choppy periods, and be suspicious of a backtest that doesn't have them

A trend-following strategy's edge specifically depends on occasional large trending moves paying for many smaller losses accumulated during non-trending periods; a backtest that doesn't show real, sometimes extended losing streaks during historically choppy market periods likely isn't accurately representing how the strategy actually behaves, and should be checked for the same lookahead or cost-modeling issues [overfitting-and-robustness-checks](../overfitting-and-robustness-checks/SKILL.md) warns about generally.

### Explicitly test whipsaw sensitivity by measuring performance specifically during known choppy historical periods

Identify historical periods that were genuinely range-bound/choppy for the instruments being traded (not just look at overall backtest performance) and measure the strategy's performance specifically during those periods. A strategy that loses an acceptable, bounded amount during choppy periods and makes it back during trending periods is behaving as expected; one that loses an amount inconsistent with its own overall risk budget during chop has a whipsaw problem that overall-period statistics alone can hide.

### Treat trailing-stop and exit design as a first-class design decision with real tradeoffs, not an afterthought

Trend-following strategies live or die on their exit logic: a trailing stop that's too tight exits real trends prematurely and gives back gains to noise; one that's too loose gives back too much of an accumulated gain before exiting a trend that's actually reversed. Test exit-rule sensitivity explicitly across a range of parameter choices and understand the actual tradeoff being made, rather than picking one exit rule because it happened to score best on a specific backtest period (which risks exactly the parameter-overfitting [overfitting-and-robustness-checks](../overfitting-and-robustness-checks/SKILL.md) warns about, applied specifically to exit logic).

### Size trend-following positions with explicit awareness of their lumpy, negatively-skewed-loss/positively-skewed-gain return shape

Standard volatility-targeting sizing (see [position-sizing-and-risk-management](../position-sizing-and-risk-management/SKILL.md)) still applies, but sizing decisions for trend-following specifically need to account for the fact that a meaningful fraction of total return typically comes from a small number of large trending moves; sizing too conservatively based on "typical" choppy-period volatility can under-size the strategy for the actual trending moves that drive most of its long-run return.

### Check correlation across the instruments actually being trend-followed, not just assume trading many markets means real diversification

A trend-following system trading many different futures or instruments is genuinely more diversified than one trading a single instrument, but the instruments still often share correlated trend drivers (a broad risk-on/risk-off macro regime moving many markets in the same direction at once), consistent with [portfolio-construction-and-correlation-checks](../portfolio-construction-and-correlation-checks/SKILL.md). Check the actual correlation of the trend signals across instruments, especially during major macro regime shifts, rather than assuming trading more instruments automatically means proportionally more diversification.

## Never do this

- Never treat a trend-following backtest with a smooth, near-continuous equity curve as good news; it's specifically suspicious for this strategy category, not just in general.
- Never evaluate whipsaw risk only from overall backtest statistics; explicitly measure performance during identified choppy historical periods.
- Never finalize exit/trailing-stop logic purely by picking whichever parameter scored best on a backtest without understanding and testing the actual tradeoff across a range of choices.
- Never size a trend-following strategy based only on "typical" period volatility without accounting for the outsized role a small number of large trending moves plays in its total return.
- Never assume trading more instruments in a trend-following system automatically produces proportional diversification without checking actual trend-signal correlation across those instruments, especially during macro regime shifts.

## Verification checklist

- [ ] The backtest shows real, extended losing streaks during historically choppy periods, and an unusually smooth equity curve has been investigated rather than accepted
- [ ] Performance has been explicitly measured during identified choppy historical periods, not only assessed from overall-period statistics
- [ ] Exit/trailing-stop logic sensitivity was tested across a range of parameter choices, with the actual tradeoff understood, rather than picked purely because one choice scored best in a backtest
- [ ] Position sizing accounts explicitly for the outsized contribution of a small number of large trending moves to total return, not just typical-period volatility
- [ ] Trend-signal correlation across traded instruments has been checked directly, especially during major macro regime shifts, rather than assumed from instrument count alone

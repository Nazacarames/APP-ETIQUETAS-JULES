# Robustness thresholds and what they indicate

These are orientation ranges, not laws of physics. A real strategy can occasionally exceed these in a short sample by luck, and a fake one can occasionally sit inside them. Use these to decide what deserves investigation, not as a pass/fail gate applied blindly.

## Sharpe ratio (annualized, out-of-sample)

| Range | Read |
|---|---|
| 0 - 1.0 | Weak or no edge on a risk-adjusted basis; may still be viable with leverage/sizing changes, but investigate before assuming it's worth trading |
| 1.0 - 2.0 | Plausible range for a real, modest systematic edge |
| 2.0 - 3.5 | Strong; plausible for a well-executed systematic strategy, especially short-holding-period or multi-asset ones, but worth extra scrutiny |
| 3.5+ sustained out-of-sample | Rare enough among real, persistent strategies that this is a red flag first, not a result to celebrate first. Check for lookahead bias, unrealistic costs, a too-short or too-favorable test window, or a strategy that is implicitly making a huge, undiversified bet that hasn't been stress-tested |

Sharpe calculated only in-sample after optimization is not meaningful evidence at all, regardless of the number; it's a measure of how well the optimizer worked, not how well the strategy will work.

## MAR ratio (CAGR / max drawdown)

| Range | Read |
|---|---|
| Under 0.5 | Poor risk-adjusted return relative to the drawdown taken to get it |
| 0.5 - 2 | Common range for real systematic strategies |
| 2 - 6 | Strong; achievable by genuinely good strategies, particularly ones with active risk management, but check the drawdown figure is real (see equity curve smoothness below) |
| 6-8+ | Uncommon enough in real, sustained trading that it usually means the backtest's measured drawdown is artificially small: check for a too-short test window that never included a real adverse period, unrealistic costs, or overfitting to a benign historical regime |

## Equity curve smoothness

A real strategy's equity curve should have real drawdowns: periods where it loses money for a while before recovering, proportional to its overall volatility and holding period. Two concrete checks:

- **Linear fit R²**: fit a straight line to the equity curve and check the R². Values above roughly 0.97-0.98 for a multi-year backtest are unusual for a real strategy and often indicate the backtest is missing real volatility, most commonly through lookahead bias or unrealistically low modeled costs.
- **Drawdown duration and depth relative to volatility**: compute the strategy's own daily/trade-level return volatility, then check whether the observed max drawdown and its duration are consistent with that volatility (a strategy with meaningful day-to-day volatility should show underwater periods of real length; if it doesn't, something in the backtest is smoothing over risk that would actually be there live).

## Number of trades vs. number of parameters

There's no single universal rule, but as an orientation: a strategy with `k` real tunable parameters (each independent rule threshold, filter, or exit condition counts, not just position-sizing constants) should be validated on a number of independent trades that is comfortably in the dozens per parameter at minimum, with more required as the parameters interact (e.g. a filter that only applies in certain regimes effectively adds parameters within parameters). A strategy validated on 50 trades with 8 tunable thresholds has not been meaningfully validated; it's been fit.

## What "investigate before celebrating" actually means in practice

When a result crosses into a red-flag range, work through, in order:
1. Re-check the data pipeline for lookahead bias (signal/execution timing, restated data, feed misalignment).
2. Re-check transaction cost and slippage assumptions, then stress-test them upward.
3. Re-check whether the test window happens to be an unusually favorable period (a strong trend with no real reversal, for instance), and re-run across a longer or different window if the data is available.
4. Re-check whether this was the single best result out of many variants tried, and if so, treat it with the added skepticism that implies.
5. Only after all four come back clean does a strong result become something worth taking seriously, and even then, the walk-forward and paper-trading steps in the main skill still apply before real capital is at risk.

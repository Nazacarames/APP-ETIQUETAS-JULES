---
name: backtest-result-authenticity-audit
description: 'Run this skill before calling any backtest "done," trustworthy, or ready to inform a sizing/allocation/go-live decision, and whenever a user asks "can I trust this backtest" or wants a final check before acting on a result. It ties together lookahead-bias-detection-methodology, fill-feasibility-and-impossible-fill-detection, order-book-and-intrabar-price-path-modeling, and backtest-vs-broker-fill-reconciliation into one mandatory, mechanical audit pass, the same way pre-launch-technical-audit ties together many individual website checks into one required pre-launch procedure. This skill exists because it''s possible to know every individual check that could catch a fake result and still skip several of them under time pressure; a single named, required audit closes that gap.'
---

# Backtest Result Authenticity Audit

## Why this matters

Every skill this one references describes a real, specific way a backtest can produce a fake or inflated result: lookahead bias, impossible fills, intrabar path ambiguity, and unvalidated fill assumptions. Knowing all of them individually doesn't guarantee all of them get checked on any given backtest, especially under the time pressure of wanting to move a promising-looking result forward. This skill exists to make "prove this result isn't fake" a single, mandatory, named procedure with explicit pass/fail criteria, run every time, rather than a set of checks that are easy to partially skip when a result looks good and there's a temptation not to look too hard at why.

## Do this

### Run the full audit sequence in [references/audit-checklist.md](references/audit-checklist.md) before treating any backtest result as trustworthy

The reference checklist sequences the mechanical tests from [lookahead-bias-detection-methodology](../lookahead-bias-detection-methodology/SKILL.md) (truncation test, future-corruption test, data-merge audit), [fill-feasibility-and-impossible-fill-detection](../fill-feasibility-and-impossible-fill-detection/SKILL.md) (volume/intrabar-range checks, low-liquidity-bar handling), [order-book-and-intrabar-price-path-modeling](../order-book-and-intrabar-price-path-modeling/SKILL.md) (where finer-grained data applies), and [backtest-vs-broker-fill-reconciliation](../backtest-vs-broker-fill-reconciliation/SKILL.md) (where real fill data exists) into one ordered procedure with a pass/fail criterion for each step, so running the audit means actually completing each check rather than a general impression of having "thought about" authenticity.

### Treat any single failed check as disqualifying until specifically resolved, not as one input averaged against the others

A backtest that passes nine of ten authenticity checks but fails the truncation test for lookahead bias doesn't have a 90%-trustworthy result; it has a specific, identified bug that inflates its reported performance by an unknown amount, and the result can't be trusted until that specific issue is fixed and the check is re-run and passes. Authenticity checks are gates, not points to average into an overall score; a real problem doesn't get diluted by other things going well.

### Record the audit's actual results, not just that it was run

Log which checks were run, what specific results they produced (not just pass/fail, but the actual truncation-test diffs, the actual fraction of fills flagged as infeasible, the actual reconciliation bias measured), and when, as part of the [strategy-research-log-and-versioning](../strategy-research-log-and-versioning/SKILL.md) record for that strategy version. An audit that was run but whose specific findings weren't recorded is much harder to trust later, and can't be usefully compared against a re-audit after a code change.

### Re-run the full audit after any change to the strategy's code, data pipeline, or backtesting engine, not just once at the end

A lookahead bug or an impossible-fill assumption can be introduced by a single code change to an otherwise-clean, already-audited strategy; treat the audit as a gate that has to be passed again after any material change, consistent with [lookahead-bias-detection-methodology](../lookahead-bias-detection-methodology/SKILL.md)'s recommendation to automate these checks as regression tests, rather than as a one-time certification that stays valid indefinitely once granted.

### Require this audit to pass before a result is used for any downstream decision (sizing, capital allocation, going live)

A backtest result that hasn't passed this audit shouldn't be feeding into [position-sizing-and-risk-management](../position-sizing-and-risk-management/SKILL.md)'s sizing calculations, [capital-allocation-and-strategy-lifecycle](../capital-allocation-and-strategy-lifecycle/SKILL.md)'s allocation decisions, or a decision to proceed to [paper-trading-and-forward-test-protocol](../paper-trading-and-forward-test-protocol/SKILL.md); make passing this audit an explicit, checked precondition for any of those downstream steps, not an assumed formality.

## Never do this

- Never treat a backtest as trustworthy without running the full authenticity audit sequence, however good the headline result looks.
- Never average a failed authenticity check against other passing checks to arrive at an overall "mostly fine" judgment; a failed check is disqualifying until specifically resolved.
- Never run the audit without recording its specific, detailed findings; a bare "audit passed" note without the underlying results can't be meaningfully reviewed or compared later.
- Never treat a single audit pass as valid indefinitely; re-run the full audit after any material change to the strategy, its data pipeline, or the backtesting engine.
- Never let a backtest result feed into sizing, allocation, or go-live decisions before it has explicitly passed this audit.

## Verification checklist

- [ ] The full audit sequence in [references/audit-checklist.md](references/audit-checklist.md) has been run in order, not partially or informally
- [ ] Every check has an explicit pass/fail result, and any failure was treated as disqualifying and resolved before proceeding, not averaged against passing checks
- [ ] The audit's specific findings (not just pass/fail) are recorded as part of the strategy's research log
- [ ] The audit has been re-run and passed again after the most recent material change to the strategy's code, data pipeline, or backtesting engine
- [ ] Passing this audit is an explicit, checked precondition before the result is used for sizing, capital allocation, or a go-live decision

See [references/audit-checklist.md](references/audit-checklist.md) for the full, ordered checklist with explicit pass/fail criteria for each step.

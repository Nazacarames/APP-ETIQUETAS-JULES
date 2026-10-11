---
name: strategy-research-log-and-versioning
description: 'Use this skill from the very start of any strategy research process, to log every variant, parameter set, and hypothesis actually tried, not just the one that ships. Also use it when a user is iterating on a strategy across many sessions and has lost track of what''s actually been tried, or when computing a deflated Sharpe ratio or PBO estimate that needs an honest trial count as input. This skill exists because statistical-significance-and-deflated-metrics and overfitting-and-robustness-checks both depend on knowing how much searching actually happened to find a result, and that number is impossible to reconstruct honestly after the fact if it wasn''t logged as it happened.'
---

# Strategy Research Log and Versioning

## Why this matters

[statistical-significance-and-deflated-metrics](../statistical-significance-and-deflated-metrics/SKILL.md) and the multiple-testing warnings throughout [overfitting-and-robustness-checks](../overfitting-and-robustness-checks/SKILL.md) both depend on an honest count of how many distinct variants, parameter sets, and hypotheses were actually tried before arriving at the one being evaluated. That number is straightforward to log as research happens and nearly impossible to reconstruct accurately after the fact from memory, especially across a research process that spans many sessions, months, or different people. Without a real log, every downstream statistical correction for multiple testing is working from a guess, not a fact.

## Do this

### Log every genuinely distinct variant tried, not just successful ones, and not just minor parameter tweaks conflated as one entry

A real log entry exists for every meaningfully distinct hypothesis, rule structure, or feature set tried, including the ones that failed or were abandoned, since those failures are exactly what a deflated significance calculation needs to count. Distinguish between a genuinely new variant (a different rule structure, a different hypothesis, a different feature set) and a minor parameter adjustment within an already-logged variant; both matter, but conflating many parameter tweaks into an undercount of "variants" understates the real trial count just as much as not logging failed attempts at all.

### Record the hypothesis, the specific rules, the data period used, and the result for every entry

A useful log entry captures enough to actually reconstruct the research decision later: what the hypothesis was, what specific rules and parameters implemented it, what data period it was tested on (in-sample, out-of-sample, or a specific walk-forward window), and what the result was, including negative or inconclusive results. A log that only records "tried X, didn't work" without the specifics needed to actually understand or reproduce what was tried isn't much more useful than no log at all.

### Version strategy code and configuration together with the results they produced

Store the exact code and configuration (parameter values, feature definitions, data snapshot or date range used) alongside each logged result, using real version control, so that any historical result can actually be reproduced later, not just remembered approximately. A result that can't be reproduced from its logged version is a result that can't be fully trusted, since there's no way to verify the log's description of what was tested actually matches what was run.

### Pin data snapshots or exact date ranges used for each test, since data itself can change over time

Data providers occasionally revise historical data (bug fixes, backfills, corporate-action corrections), and a result logged against "the data as of whenever this ran" without pinning the actual snapshot or exact date range used can become subtly unreproducible even with the strategy code perfectly versioned. Record the actual data snapshot, version, or exact date range used for each test as part of what gets logged and versioned.

### Review the log periodically to check for patterns across attempts, not just to count them

Beyond just counting trials for a deflated-significance calculation, periodically reviewing the actual log for patterns (does a certain type of feature or hypothesis keep failing in a similar way, is a lot of effort being spent re-testing variations of the same already-falsified idea) surfaces useful research direction that a log which only exists to be counted, and is never actually read, would miss entirely.

## Never do this

- Never rely on memory to reconstruct how many variants were tried when a deflated significance or PBO calculation needs that count; log trials as they happen.
- Never log only successful or promising variants; failed and abandoned attempts are exactly what the multiple-testing correction needs counted.
- Never conflate many parameter tweaks within one variant into a single log entry in a way that understates the real number of distinct things actually tried.
- Never log a result without also versioning the exact code, configuration, and data snapshot/date range that produced it; an unreproducible logged result can't be fully trusted.
- Never let a research log exist only to be counted and never actually reviewed for patterns across attempts.

## Verification checklist

- [ ] Every genuinely distinct variant, hypothesis, or feature set tried is logged, including failed and abandoned attempts, not just the one that shipped
- [ ] Each log entry records the hypothesis, specific rules/parameters, data period used, and result in enough detail to actually reconstruct the decision later
- [ ] Strategy code and configuration are versioned together with the results they produced, using real version control
- [ ] The exact data snapshot or date range used for each test is recorded, accounting for the possibility that provider data itself gets revised over time
- [ ] The research log is periodically reviewed for patterns across attempts, not maintained only to produce a trial count

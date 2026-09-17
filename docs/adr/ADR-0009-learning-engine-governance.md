# ADR-0009 — Learning Engine governance

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-09

## Context

Decision outcomes can reveal systematic errors, but automatic self-modification creates uncontrolled strategy drift, overfitting, and authority escalation.

## Decision

Learning Engine may evaluate mature Decisions, identify patterns, and create versioned StrategyProposals containing Evidence, hypothesis, diff, expected mechanism, side effects, evaluation windows, backtest, shadow results, rollback conditions, and human-review state.

It has no permission or code path to approve, merge, deploy, or activate Policy, Strategy, Prompt, threshold, weight, schema, or code changes. Activation requires explicit human approval after out-of-sample backtest and shadow evaluation.

## Alternatives considered

### Automatic prompt or rule optimization

Rejected because short-term outcomes and correlated samples would cause silent strategy drift.

### No learning loop

Rejected because it would leave Decision Journal outcomes unused.

## Consequences

Improvement is slower but reviewable and reversible. Poor or rejected proposals remain available for audit.

## Security and operational impact

Learning tools are read-heavy and cannot access deployment, source write, or approval credentials. Evaluation enforces `available_at`, costs, regime splits, and leakage checks.

## Migration and rollback

PR-09 introduces proposal-only permissions. Strategy activation is a separate human-authorized application use case.

## References

- Master Spec sections 8.4, 15, S11

# ADR-0007 — Deterministic position sizing

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-06

## Context

Precise position size is a constrained financial calculation. Allowing an LLM to choose percentages would be irreproducible and could bypass portfolio caps.

## Decision

Portfolio Manager emits only `NONE|TINY|SMALL|NORMAL|HIGH|EXIT`. A pure, versioned PositionSizing Engine maps intent and immutable snapshots to Decimal weights and quantities. It applies single-name, sector, gross exposure, cash, risk-budget, liquidity, pending-order, Core/Tactical, Veto, lot-size, and lower-risk rounding constraints.

Every run stores formula version, canonical input, input hash, every binding cap, pre/post-rounding values, and reason codes. Identical inputs and formula version must produce bit-identical Decimal results.

## Alternatives considered

### LLM target percentage

Rejected because it is nondeterministic and cannot prove cap compliance.

### One composite score-to-size formula

Rejected because it conflates Thesis, Timing, Portfolio, and Risk and obscures gates.

## Consequences

The formula is less flexible conversationally but is testable, replayable, and safe. Policy changes require new versions.

## Security and operational impact

Sizing runs have no external write authority. All caps fail closed on missing input. Property tests cover upper bounds and lower-risk rounding.

## Migration and rollback

PR-06 introduces formula v1. New formulas are separate versions; historical Decisions retain their original run.

## References

- Master Spec sections 10, 11, S4, S6, S7

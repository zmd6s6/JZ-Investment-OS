# ADR-0005 — Two-round investment committee protocol

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-05

## Context

Independent specialist views reduce blind spots, but unbounded multi-agent debate creates anchoring, cost, latency, and non-termination. Simple voting hides substantive disagreements.

## Decision

Round 1 runs Macro, Industry, Fundamental, Market/Quant, and Event independently against one frozen AnalysisContext. A deterministic-first Conflict Detector identifies material disagreement. Round 2 is targeted only at those conflicts and always includes Devil's Advocate review. The committee ends after Round 2 and records unresolved conflict.

Portfolio Manager then outputs portfolio fit and `risk_intent`; Risk Manager applies PASS/VETO; deterministic gates and sizing run; CIO produces the allowed final recommendation. Voting or average scores cannot replace this sequence.

## Alternatives considered

### Single synthesizer prompt

Rejected because it removes independent evidence lanes and makes omissions hard to detect.

### Unlimited debate until consensus

Rejected because consensus can be artificial and execution becomes unbounded.

## Consequences

The protocol has predictable maximum cost and preserves dissent. Some conflicts will remain unresolved and must be exposed to the human.

## Security and operational impact

Each role has a fixed tool allowlist, timeout, and token budget. Failed roles are explicit; one Agent cannot impersonate another.

## Migration and rollback

PR-05 implements versioned sessions and messages. Protocol changes require a new committee protocol version and ADR.

## References

- Master Spec sections 4, 9, S9

# ADR-0004 — Structured agent schema and model gateway

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-05

## Context

Runtime Agents need provider-independent execution and machine-verifiable communication. Free-form reports cannot reliably enforce Evidence, confidence, role authority, or downstream decision invariants.

## Decision

All model calls pass through `LLMGatewayPort`. Agent outputs use versioned, strict Pydantic/JSON Schema, including AgentOpinion. A factual observation requires Evidence IDs. Validation may attempt at most two schema repairs with explicit errors; after that the run fails as `INSUFFICIENT_DATA` and raw text is not promoted to an opinion.

Record provider, model, parameters, Prompt version/hash, tool allowlist, input snapshot hash, validated output, usage, latency, retries, and sanitized raw-output reference.

## Alternatives considered

### Provider SDKs inside each Agent

Rejected because it couples roles to vendors and prevents centralized budgets, tracing, and safety policy.

### Markdown as the internal protocol

Rejected because prose cannot provide stable validation or compatibility.

## Consequences

Schemas require versioning and migrations. Provider changes become adapter work rather than domain rewrites.

## Security and operational impact

Gateway tools use least privilege, bounded cost/timeout, redacted traces, and prompt-injection isolation. Model output is untrusted until schema and domain validation pass.

## Migration and rollback

PR-05 introduces v1 schemas. Breaking changes create a new schema version with explicit readers for retained historical output.

## References

- Master Spec sections 4, 6, 15, and 16.1

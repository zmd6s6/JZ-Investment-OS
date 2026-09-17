# ADR-0011 — Pure domain kernel and strict Policy boundary

- Status: Accepted
- Date: 2026-09-17
- Deciders: Master Spec constraints; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-01

## Context

PR-01 needs exact financial values, governed state transitions, and a strict Investment Policy
protocol. The domain layer must remain independent of Pydantic and other frameworks, while JSON
inputs still need a versioned schema and fail-closed validation.

## Decision

Use frozen, slotted standard-library dataclasses, `StrEnum`, `Decimal`, and timezone-aware value
objects inside `investment_os.domain`. Domain constructors enforce invariants even when an input
adapter is bypassed. State machines use closed transition tables and explicit guard contexts; a
successful transition returns an immutable record with machine-readable reason codes and UTC time.

Place the strict Pydantic v2 `InvestmentPolicySchema` in the application layer. It rejects unknown
fields, unsafe V1 execution settings, and inconsistent cross-field limits, then converts percentages
to domain `Weight` values. Commit the generated JSON Schema as
`docs/schemas/investment-policy-v1.json` and check drift in CI.

The shipped policy is `TEST_DEFAULT`. It is test configuration only and cannot become `ACTIVE`
without a complete, explicitly attributed human approval record.

## Alternatives considered

### Pydantic domain entities

Rejected because validation-framework types would leak into the framework-free domain and make the
core depend on transport concerns.

### Unstructured dictionaries and conditional state updates

Rejected because unknown fields, implicit transitions, and stringly typed guards would weaken
auditability and fail-closed behavior.

### Binary floating-point percentages

Rejected because exact equality and reproducibility are required for financial rules and Core plus
Tactical invariants.

## Consequences

Domain rules can be tested without infrastructure and are deterministic for equal inputs. Boundary
models duplicate a small amount of structure, but the explicit conversion prevents framework and
wire-format concerns from controlling business invariants. Schema changes require versioning and a
generated artifact update.

## Security and operational impact

Unknown Policy fields and unsafe execution flags fail validation. Learning Engine authority is
represented in strategy-transition guards and cannot approve or activate proposals. No live-trading,
external-data, database, or model capability is introduced.

## Migration and rollback

PR-01 adds no database migration and stores no production state. Roll back the domain modules,
Policy Schema/config, tests, and generated schema together. Future wire incompatibility must use a
new schema version and an ADR rather than silently changing version `1.0`.

## References

- Master Spec sections 2.4, 2.5, 7, 8, 10, 15, 18, and PR-01
- `src/investment_os/domain/`
- `src/investment_os/application/policy_schema.py`
- `tests/unit/test_state_machines.py`
- `tests/property/test_domain_properties.py`

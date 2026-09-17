# Architecture Decision Records

ADRs capture consequential decisions that the Master Spec leaves to implementation. They explain decisions; they cannot weaken the Master Spec.

## Numbering and filenames

Use `ADR-NNNN-short-kebab-title.md`. Reserve ADR-0001 through ADR-0010 for the decisions required by the Master Spec. Never reuse a number.

## Status

- `Proposed`: under review; not authoritative.
- `Accepted`: active and authoritative within its scope.
- `Rejected`: considered and not selected.
- `Superseded by ADR-NNNN`: replaced; retained for history.
- `Deprecated`: no longer recommended but not yet replaced.

Only a human-approved governance decision may accept an ADR that changes investment behavior, risk, approval, live execution, strategy activation, or data authorization. Codex may accept routine implementation ADRs when fully bounded by the Master Spec, but must surface material trade-offs in the stage report.

## Required structure

Copy `ADR-0000-template.md`. Each ADR must contain Context, Decision, Alternatives, Consequences, Security/Operational Impact, Migration/Rollback, and References. Accepted ADRs are immutable; supersede rather than rewrite the decision.

"""Immutable role and prompt-bundle registration for bounded Agent execution."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.agent import AgentRole, AgentTool
from investment_os.domain.errors import DomainError, DomainErrorCode


def _require_nonempty(value: str, field: str) -> str:
    if not value.strip():
        raise DomainError(DomainErrorCode.INVARIANT_VIOLATION, f"{field} must not be blank")
    return value


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class PromptBundle:
    """Versioned prompt provenance and least-privilege capabilities for one fixed role."""

    role: AgentRole
    version: str
    content_hash: str
    allowed_tools: tuple[AgentTool, ...]

    def __post_init__(self) -> None:
        _require_nonempty(self.version, "version")
        if not _is_sha256(self.content_hash):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "content_hash must be a lowercase SHA-256 hex digest",
            )
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise DomainError(
                DomainErrorCode.INVARIANT_VIOLATION,
                "allowed_tools must not contain duplicates",
            )


class AgentRoleRegistry:
    """Lookup-only registry; callers cannot change a role's prompt or capability set."""

    def __init__(self, bundles: tuple[PromptBundle, ...]) -> None:
        registrations: dict[AgentRole, PromptBundle] = {}
        for bundle in bundles:
            if bundle.role in registrations:
                raise DomainError(
                    DomainErrorCode.INVARIANT_VIOLATION,
                    f"role {bundle.role} has more than one prompt bundle",
                )
            registrations[bundle.role] = bundle
        self._by_role: Mapping[AgentRole, PromptBundle] = MappingProxyType(registrations)

    @property
    def bundles(self) -> tuple[PromptBundle, ...]:
        """Registered bundles in deterministic role order for audit recording."""

        return tuple(self._by_role[role] for role in sorted(self._by_role, key=str))

    def require(self, role: AgentRole) -> PromptBundle:
        """Return a registered role or fail closed before any gateway request occurs."""

        try:
            return self._by_role[role]
        except KeyError as exc:
            raise ApplicationError(
                ApplicationErrorCode.AGENT_ROLE_UNREGISTERED,
                "Agent role is not registered for this runtime",
                details={"role": role.value},
            ) from exc

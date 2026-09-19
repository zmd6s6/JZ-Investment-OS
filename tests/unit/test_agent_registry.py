"""Tests for immutable, least-privilege Agent prompt registration."""

import pytest

from investment_os.application.agent_registry import AgentRoleRegistry, PromptBundle
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.domain.agent import AgentRole, AgentTool
from investment_os.domain.errors import DomainError


def _bundle(
    role: AgentRole = AgentRole.MACRO,
    *,
    allowed_tools: tuple[AgentTool, ...] = (AgentTool.RETRIEVE_EVIDENCE,),
) -> PromptBundle:
    return PromptBundle(
        role=role,
        version="v1",
        content_hash="a" * 64,
        allowed_tools=allowed_tools,
    )


def test_registry_returns_fixed_prompt_provenance_and_tool_allowlist() -> None:
    bundle = _bundle()
    registry = AgentRoleRegistry((bundle,))

    assert registry.require(AgentRole.MACRO) is bundle
    assert registry.bundles == (bundle,)
    assert registry.require(AgentRole.MACRO).allowed_tools == (AgentTool.RETRIEVE_EVIDENCE,)


def test_registry_rejects_duplicate_role_registration() -> None:
    with pytest.raises(DomainError, match="more than one"):
        AgentRoleRegistry((_bundle(), _bundle()))


@pytest.mark.parametrize(
    ("content_hash", "allowed_tools"),
    [
        ("A" * 64, (AgentTool.RETRIEVE_EVIDENCE,)),
        ("a" * 63, (AgentTool.RETRIEVE_EVIDENCE,)),
        ("a" * 64, (AgentTool.READ_THESIS, AgentTool.READ_THESIS)),
    ],
)
def test_prompt_bundle_rejects_invalid_hash_or_duplicate_capability(
    content_hash: str, allowed_tools: tuple[AgentTool, ...]
) -> None:
    with pytest.raises(DomainError):
        PromptBundle(
            role=AgentRole.EVENT,
            version="v1",
            content_hash=content_hash,
            allowed_tools=allowed_tools,
        )


def test_registry_fails_closed_for_an_unregistered_role() -> None:
    registry = AgentRoleRegistry((_bundle(),))

    with pytest.raises(ApplicationError) as error:
        registry.require(AgentRole.DEVILS_ADVOCATE)

    assert error.value.code is ApplicationErrorCode.AGENT_ROLE_UNREGISTERED
    assert error.value.details == {"role": "DEVILS_ADVOCATE"}

"""Versioned bootstrap health response schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LivenessResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    service: Literal["investment-api"] = "investment-api"
    status: Literal["alive"] = "alive"
    mode: Literal["DEVELOPMENT"] = "DEVELOPMENT"
    live_trading: Literal[False] = False


class ReadinessResponse(StrictResponse):
    schema_version: Literal["1.0"] = "1.0"
    service: Literal["investment-api"] = "investment-api"
    status: Literal["ready", "not_ready"]
    mode: Literal["DEVELOPMENT"] = "DEVELOPMENT"
    live_trading: Literal[False] = False
    checks: dict[str, str]

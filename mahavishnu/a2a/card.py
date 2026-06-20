from __future__ import annotations

from pydantic import BaseModel


class A2ACapabilities(BaseModel):
    model_config = {"extra": "forbid"}

    streaming: bool = False
    pushNotifications: bool = False  # noqa: N815 — A2A protocol field name


class A2ASkill(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    name: str
    description: str


class AgentCard(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    description: str
    url: str
    version: str
    capabilities: A2ACapabilities = A2ACapabilities()
    skills: list[A2ASkill] = []

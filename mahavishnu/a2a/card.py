from __future__ import annotations

from pydantic import BaseModel


class A2ACapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False  # noqa: N815 — A2A protocol field name


class A2ASkill(BaseModel):
    id: str
    name: str
    description: str


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str
    capabilities: A2ACapabilities = A2ACapabilities()
    skills: list[A2ASkill] = []

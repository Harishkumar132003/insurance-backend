from typing import Any

from pydantic import BaseModel


class WorkflowRunRequest(BaseModel):
    input: dict[str, Any]


class StepDebug(BaseModel):
    step: str
    resolved_url: str | None = None
    resolved_headers: dict[str, Any] | None = None
    resolved_body: dict[str, Any] | None = None
    response: Any = None
    error: str | None = None


class WorkflowRunResponse(BaseModel):
    data: dict[str, Any]
    prompt: str | None = None
    steps_debug: list[StepDebug]

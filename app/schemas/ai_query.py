from typing import Any

from pydantic import BaseModel, Field


class AiQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000,
                          description="Natural-language question about this hospital's data.")


class AiQueryResponse(BaseModel):
    answer: str = Field(..., description="Human-readable answer.")
    sql: list[str] = Field(default_factory=list,
                           description="SQL statement(s) the agent executed (for transparency).")
    columns: list[str] = Field(default_factory=list,
                               description="Columns of the last result set.")
    rows: list[dict[str, Any]] = Field(default_factory=list,
                                       description="Rows of the last result set (capped).")

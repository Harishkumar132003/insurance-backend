from datetime import datetime

from pydantic import BaseModel


class ClaimCaseDocumentResponse(BaseModel):
    id: int
    claim_case_id: int
    original_filename: str
    content_type: str | None = None
    file_size: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

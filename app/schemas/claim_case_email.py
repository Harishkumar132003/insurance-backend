from datetime import datetime

from pydantic import BaseModel


class ClaimCaseEmailAttachmentResponse(BaseModel):
    id: int
    original_filename: str
    content_type: str | None = None
    file_size: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClaimCaseEmailResponse(BaseModel):
    id: int
    claim_case_id: int
    direction: str
    email_type: str | None = None
    from_email: str
    to_email: str
    subject: str | None = None
    body: str | None = None
    email_date: datetime | None = None
    created_at: datetime
    attachments: list[ClaimCaseEmailAttachmentResponse] = []

    model_config = {"from_attributes": True}


class ClaimCaseEmailListResponse(BaseModel):
    id: int
    direction: str
    email_type: str | None = None
    from_email: str
    to_email: str
    subject: str | None = None
    email_date: datetime | None = None
    created_at: datetime
    attachment_count: int = 0

    model_config = {"from_attributes": True}

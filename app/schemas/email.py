from pydantic import BaseModel


class SendEmailResponse(BaseModel):
    message: str
    to_email: str
    subject: str
    status: str


class InboxEmailResponse(BaseModel):
    id: str
    from_email: str
    subject: str
    date: str
    body: str

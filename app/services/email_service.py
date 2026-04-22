import imaplib
import smtplib
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import decode_header

from fastapi import HTTPException, status

from app.core.config import settings


def send_email(
    from_email: str,
    from_password: str,
    to_email: str,
    subject: str,
    body: str,
    attachments: list[tuple[bytes, str, str]] | None = None,
    cc_emails: list[str] | None = None,
) -> None:
    """Send an email via the sender's own Gmail SMTP credentials.

    Args:
        from_email:    The sender's email address (e.g. the hospital's mailbox).
        from_password: Plaintext Gmail app password for `from_email`.
        attachments:   List of (file_bytes, filename, content_type) tuples.
        cc_emails:     List of CC email addresses.
    """
    if not from_email or not from_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sender email credentials are missing",
        )

    msg = MIMEMultipart("mixed")
    msg["From"] = from_email
    msg["To"] = to_email
    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    if attachments:
        for file_bytes, filename, content_type in attachments:
            maintype, _, subtype = content_type.partition("/")
            if not subtype:
                subtype = "octet-stream"
            part = MIMEApplication(file_bytes, _subtype=subtype)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

    recipients = [to_email] + (cc_emails or [])

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_email, from_password)
            server.sendmail(from_email, recipients, msg.as_string())
    except smtplib.SMTPException as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send email: {str(e)}",
        )


def render_form_data_html(form_data, template) -> str:
    return template.html_content or ""


def fetch_inbox(limit: int = 10) -> list[dict]:
    if not settings.EMAIL_ADDRESS or not settings.EMAIL_APP_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email credentials not configured",
        )

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(settings.EMAIL_ADDRESS, settings.EMAIL_APP_PASSWORD)
        mail.select("INBOX")

        _, message_numbers = mail.search(None, "ALL")
        email_ids = message_numbers[0].split()

        # Get latest N emails
        email_ids = email_ids[-limit:] if len(email_ids) > limit else email_ids
        email_ids.reverse()  # newest first

        emails = []
        for eid in email_ids:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw_email)

            subject = _decode_header(msg["Subject"])
            from_email = _decode_header(msg["From"])
            date = msg["Date"] or ""

            body = _extract_body(msg)

            emails.append({
                "id": eid.decode(),
                "from_email": from_email,
                "subject": subject,
                "date": date,
                "body": body,
            })

        mail.logout()
        return emails

    except imaplib.IMAP4.error as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch emails: {str(e)}",
        )


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(errors="replace")
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(errors="replace")
    return ""

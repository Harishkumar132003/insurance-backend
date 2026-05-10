import html
import imaplib
import smtplib
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import decode_header
from email.utils import make_msgid

from fastapi import HTTPException, status

from app.core.config import settings


def _build_email_body_parts(body: str) -> tuple[str, str]:
    """Return (plain_text, html) representations of a body composed with `\\n`
    newlines. The plain-text part preserves the original formatting verbatim.
    The HTML part HTML-escapes the body and converts newlines to <br> so
    Gmail / Outlook render the same line breaks the user sees in the preview
    instead of collapsing whitespace into a single sentence.
    """
    plain = body or ""
    # Normalise CRLF → LF before escaping so a single newline always becomes
    # a single <br>.
    normalized = plain.replace("\r\n", "\n").replace("\r", "\n")
    escaped = html.escape(normalized).replace("\n", "<br>")
    html_body = (
        '<div style="font-family:Arial,sans-serif;font-size:14px;'
        'line-height:1.55;color:#111827;white-space:normal;">'
        f"{escaped}"
        "</div>"
    )
    return plain, html_body


def send_email(
    from_email: str,
    from_password: str,
    to_email: str,
    subject: str,
    body: str,
    attachments: list[tuple[bytes, str, str]] | None = None,
    cc_emails: list[str] | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
) -> str:
    """Send an email via the sender's own Gmail SMTP credentials.

    Args:
        from_email:    The sender's email address (e.g. the hospital's mailbox).
        from_password: Plaintext Gmail app password for `from_email`.
        attachments:   List of (file_bytes, filename, content_type) tuples.
        cc_emails:     List of CC email addresses.
        in_reply_to:   Message-ID of the email being replied to (RFC 5322 format,
                       including angle brackets, e.g. "<abc@host>"). Sets the
                       In-Reply-To header so Gmail/Outlook thread the reply
                       under the original message.
        references:    Ordered list of Message-IDs from the entire thread (root
                       through previous reply). Sets the References header.

    Returns:
        The Message-ID assigned to the outgoing email (RFC 5322 format with
        angle brackets), so the caller can persist it for future threading.
    """
    if not from_email or not from_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sender email credentials are missing",
        )

    # Generate a stable Message-ID using the sender's domain so receiving MTAs
    # don't flag it as suspicious.
    domain = from_email.split("@", 1)[1] if "@" in from_email else "oasys.local"
    message_id = make_msgid(domain=domain)

    msg = MIMEMultipart("mixed")
    msg["From"] = from_email
    msg["To"] = to_email
    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)

    # multipart/alternative inside multipart/mixed is the standard layout for
    # an email that has both plain-text + HTML bodies and attachments.
    plain_body, html_body = _build_email_body_parts(body)
    body_alt = MIMEMultipart("alternative")
    body_alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    body_alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(body_alt)

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

    return message_id


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

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
    to_email: str,
    subject: str,
    body: str,
    pdf_data: bytes | None = None,
    pdf_filename: str = "form.pdf",
) -> None:
    if not settings.EMAIL_ADDRESS or not settings.EMAIL_APP_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email credentials not configured",
        )

    msg = MIMEMultipart("mixed")
    msg["From"] = settings.EMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    if pdf_data:
        pdf_part = MIMEApplication(pdf_data, _subtype="pdf")
        pdf_part.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        msg.attach(pdf_part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.EMAIL_ADDRESS, settings.EMAIL_APP_PASSWORD)
            server.sendmail(settings.EMAIL_ADDRESS, to_email, msg.as_string())
    except smtplib.SMTPException as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send email: {str(e)}",
        )


def render_form_data_html(form_data, template) -> str:
    sections = template.schema_json.get("sections", [])
    data = form_data.data_json or {}

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
            h3 {{ color: #34495e; margin-top: 20px; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
            th {{ background-color: #3498db; color: white; width: 35%; }}
            td {{ background-color: #f9f9f9; }}
        </style>
    </head>
    <body>
        <h2>{template.name} (v{template.version})</h2>
        <p><strong>Claim Case ID:</strong> {form_data.claim_case_id}</p>
        <p><strong>Status:</strong> {form_data.status}</p>
    """

    for section in sections:
        section_name = section.get("name", "")
        section_label = section.get("label", section_name.replace("_", " ").title())
        section_data = data.get(section_name, {})

        html += f"<h3>{section_label}</h3><table>"

        for field in section.get("fields", []):
            key = field["key"]
            label = field.get("label", key.replace("_", " ").title())
            value = section_data.get(key, "—") if isinstance(section_data, dict) else "—"

            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)

            html += f"<tr><th>{label}</th><td>{value}</td></tr>"

        html += "</table>"

    html += "</body></html>"
    return html


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

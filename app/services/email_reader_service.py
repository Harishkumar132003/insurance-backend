import imaplib
import io
import json
import logging
import re
import email as email_lib
from email.header import decode_header
from email.utils import parsedate_to_datetime

from openai import OpenAI
from PyPDF2 import PdfReader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.claim_case import ClaimCase
from app.models.claim_case_email import ClaimCaseEmail
from app.models.claim_case_email_attachment import ClaimCaseEmailAttachment
from app.models.policy_provider_config import PolicyProviderConfig
from app.services.document_extraction_service import extract_documents
from app.utils.file_storage import save_attachment

logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "APPROVED", "PARTIALLY_APPROVED", "DENIED",
    "ENHANCEMENT_APPROVED", "ENHANCEMENT_DENIED", "ADR_NMI", "UNKNOWN",
}

# Claim stage (post-treatment cashless claim) has no enhancement loop — the
# claim is judged on the final bill once. The extractor for claim replies
# uses this narrower set.
CLAIM_VALID_STATUSES = {
    "APPROVED", "PARTIALLY_APPROVED", "DENIED", "ADR_NMI", "UNKNOWN",
}

OPENAI_PROMPT = """
You are an expert in Indian health insurance claim processing.

Your job is to classify the CURRENT STATUS of a claim from an email and its attachments.

---

Return STRICT JSON:

{{
  "claim_number": "string or null",
  "uhid": "string or null",
  "status": "APPROVED | PARTIALLY_APPROVED | DENIED | ENHANCEMENT_APPROVED | ENHANCEMENT_DENIED | ADR_NMI | UNKNOWN",
  "approved_amount": "number or null — see the approved_amount rule below",
  "summary": "1-2 line summary",
  "query_details": "if ADR_NMI, describe what is being asked or what documents are needed. null otherwise",
  "documents_requested": "if ADR_NMI and specific documents are listed, provide a comma-separated string. null otherwise",
  "documents_list": [],
  "denial_reason": "string or null — see the denial_reason rule below"
}}

`documents_list` rules:
- Only populate when status is ADR_NMI.
- Each element must be a single canonical document name as a STRING (never an object, never a description).
- Examples of canonical names: "Discharge Summary", "Final Bill", "Investigation Reports",
  "Indoor Case Papers", "Operative Notes", "Pharmacy Bills", "Lab Reports", "ICP".
- Trim each entry. Merge near-duplicates. Do NOT wrap descriptions inside the array.
- Return [] if status is not ADR_NMI or no specific documents are being asked for.

`approved_amount` rule:
- Populate for APPROVED, PARTIALLY_APPROVED, or ENHANCEMENT_APPROVED; null otherwise.
- For APPROVED / PARTIALLY_APPROVED: the sanctioned / authorized amount in this letter.
- For ENHANCEMENT_APPROVED: the ENHANCEMENT / ADDITIONAL amount being granted (the
  delta), NOT the cumulative "Total Authorised" figure. e.g. if the letter says
  "Enhancement Amount Approved: Rs.10,000" and "Total Cumulative Authorized:
  Rs.87,200", return 10000 — the backend adds it onto the running total.
- Plain number only — no commas or currency symbols.

`denial_reason` rule:
- Populate ONLY when status is DENIED or ENHANCEMENT_DENIED; null for every other status.
- 1-2 short sentences quoting the insurer's stated rationale. Do not editorialise or paraphrase.
- Examples: "Treatment falls under policy exclusion clause 4.2 (cosmetic procedures).",
  "Pre-existing disease not disclosed at policy inception.",
  "Enhancement not warranted — clinical justification insufficient."

---

IMPORTANT RULES (VERY STRICT):

1. APPROVED — use ONLY when ALL of these hold:
   a. This is the FIRST approval on the thread (no prior authorization /
      sanctioned amount; not a reply to an earlier approval letter).
   b. The authorized / sanctioned amount equals the FULL claimed / billed /
      estimated amount — i.e. NOTHING is being deducted or withheld.
   c. There is NO co-pay, NO deductible, NO discount, NO sub-limit cap, and
      NO "non-admissible" deduction reducing the authorized figure.
   d. Approval language is present ("cashless authorization", "authorization
      letter", "claim approved", "authorization granted", "final approval", etc.).
   If the email is replying to a prior authorization (quoted earlier approval,
   mentions an existing auth/claim number with a sanctioned amount, letter
   labelled "Enhancement"), use ENHANCEMENT_APPROVED instead — see rule 4.

2. PARTIALLY_APPROVED — use whenever approval IS granted but the authorized /
   sanctioned amount is LESS than the total bill / claimed / estimated amount,
   for ANY reason. This is the default for almost every real authorization
   letter. Triggers (any one is enough):
   - explicit wording: "partially approved", "approved in part",
     "approved at X% of estimated cost", "80% approved", "20% co-pay"
   - a Co-Pay line (percentage or amount) reducing the payable figure
   - a Deductible, Discount, "Other Deductions", or "non-admissible amount" row
   - a sub-limit cap (room rent cap, package cap, etc.) cutting the amount
   - the bottom-line "Total Authorised Amount" being smaller than the
     "Total Bill Amount" / estimated cost
   IMPORTANT: a line-item "Status: APPROVED" or the word "APPROVED" inside the
   letter does NOT make it a full APPROVED. Look at the BOTTOM-LINE numbers:
   if Total Authorised < Total Bill (e.g. 77,200 authorised out of a 96,500
   bill with a 20% co-pay), the status is PARTIALLY_APPROVED — even though the
   letter says "APPROVED" and "cashless authorization". (First approval only;
   a later partial bump is ENHANCEMENT_APPROVED.)
   When in doubt between APPROVED and PARTIALLY_APPROVED, choose
   PARTIALLY_APPROVED.

3. DENIED only if the ENTIRE claim is rejected up-front (no prior approval
   on the thread, no money already sanctioned). Signals:
   - "rejected"
   - "denied"
   - "not payable"
   - "claim not admissible"
   If the email is REPLYING to a previous authorization / partial approval
   ("Re: ... Cashless Authorization", quoted prior approval letter, mention
   of an existing claim/auth number with a sanctioned amount), DO NOT use
   DENIED — use ENHANCEMENT_DENIED instead. The backend will also coerce
   DENIED → ENHANCEMENT_DENIED whenever a prior approved amount exists, so
   prefer ENHANCEMENT_DENIED whenever in doubt.

4. ENHANCEMENT_APPROVED if an enhancement / additional / top-up request is
   APPROVED — extra amount granted on top of a prior authorization. Signals:
   - "enhancement approved" / "enhancement of Rs.X approved"
   - "additional authorization" / "additional amount sanctioned"
   - "extension approved" on an already-authorized claim
   - letter labelled "Cashless Authorization Letter - Enhancement" / "Enhancement (Approved)"
   - a reply to a prior auth that grants more money
   Use ENHANCEMENT_APPROVED (NOT APPROVED) whenever the original approval
   already stands and this email grants an enhancement. Put the enhancement
   delta in approved_amount (see the approved_amount rule).

5. ENHANCEMENT_DENIED if an enhancement / additional / top-up request was
   rejected (the previously approved base amount remains intact). Typical
   signals:
   - "enhancement request denied" / "enhancement rejected"
   - "additional amount not payable" / "no further enhancement"
   - "top-up rejected" / "extension declined"
   - The email replies to a prior enhancement submission and refuses the
     extra amount.
   Use ENHANCEMENT_DENIED (NOT DENIED) whenever the original approval still
   stands and only the new ask is being refused — the hospital can re-file
   the enhancement after this status.

6. ADR_NMI (Additional Document Request / Need More Info / query) if:
   - "additional documents required"
   - "please submit documents"
   - "documents required"
   - "need bills/reports"
   - "clarification required"
   - "please clarify"
   - "query"
   - "discrepancy"
   - Any request for extra documents, additional information, or clarification.

7. If unsure → UNKNOWN

---

EXTRACTION RULES:

- claim_number → look for:
  "Claim Number", "Reference Number", "Preauth Number", "Authorization Number"

- uhid → look for:
  "ID/TPA/Insured Id of the Patient", "Member ID", "Insured ID", "Patient ID", "UHID", "TPA ID"

- approved_amount → look for:
  "Approved Amount", "Sanctioned Amount", "Authorized Amount", "Cashless Approved Amount"
  Extract as a plain number (no commas or currency symbols). Return null if status is not APPROVED or amount not found.

READ THE FULL EMAIL BODY AND ALL ATTACHED DOCUMENT CONTENT CAREFULLY before extracting.

---

Email:
Subject: {subject}
From: {from_email}
Body and Attachments:
{body}

Return ONLY valid JSON, no other text.
"""


def process_unread_emails():
    """Main function called by the scheduler every 2 minutes."""
    if not settings.EMAIL_ADDRESS or not settings.EMAIL_APP_PASSWORD:
        logger.warning("Email credentials not configured, skipping email check")
        return

    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured, skipping email check")
        return

    logger.info("📬 Checking inbox for unread emails...")
    db = SessionLocal()
    try:
        emails = _fetch_unread_emails()
        if not emails:
            logger.info("No unread emails found")
            return

        logger.info(f"Found {len(emails)} unread email(s), processing...")

        for email_data in emails:
            try:
                logger.info(f"Processing email: subject='{email_data.get('subject', '')}', from='{email_data.get('from_email', '')}'")
                _process_single_email(db, email_data)
            except Exception as e:
                logger.error(f"Error processing email '{email_data.get('subject', '')}': {e}")
    except Exception as e:
        logger.error(f"Error in email reader: {e}")
    finally:
        db.close()


def _extract_thread_id(subject: str) -> str | None:
    """Extract thread_id from subject like 'Re: Pre-Auth Request [a1b2c3d4e5f6]'."""
    match = re.search(r'\[([a-f0-9]{12})\]', subject)
    if match:
        return match.group(1)
    return None


def _process_single_email(db: Session, email_data: dict):
    """Process a single email: analyze with OpenAI, match ClaimCase, update status."""
    subject = email_data.get("subject", "")
    from_email = email_data.get("from_email", "")
    body = email_data.get("body", "")

    # 1. Try to match by thread_id in subject first
    thread_id = _extract_thread_id(subject)
    claim_case = None
    if thread_id:
        claim_case = (
            db.query(ClaimCase)
            .filter(ClaimCase.thread_id == thread_id, ClaimCase.status.in_(AWAITING_PROVIDER_STATUSES))
            .first()
        )
        if claim_case:
            logger.info(f"Matched ClaimCase #{claim_case.id} by thread_id={thread_id}")

    # 2. Call the right OpenAI extractor based on the matched case's stage.
    # When we don't yet have a case (thread_id miss → uhid/claim_number
    # fallback below), we use the pre-auth extractor — it produces uhid /
    # claim_number which the fallback matcher needs. If that fallback ends up
    # picking a claim-stage case, _persist_email_record coerces the email_type
    # to the CLAIM_* equivalent.
    is_claim_stage = bool(claim_case and claim_case.current_stage == "CLAIM")
    if is_claim_stage:
        result = _analyze_claim_email_with_openai(subject, body, from_email)
    else:
        result = _analyze_email_with_openai(subject, body, from_email)
    if not result:
        logger.warning(f"Could not analyze email: {subject}")
        return

    extracted_status = result.get("status", "UNKNOWN")
    uhid = result.get("uhid")
    claim_number = result.get("claim_number")
    approved_amount = result.get("approved_amount")
    summary = result.get("summary", "")
    query_details = result.get("query_details")
    documents_requested = result.get("documents_requested")
    documents_list = result.get("documents_list")
    if documents_list is not None and not isinstance(documents_list, list):
        documents_list = None
    # Claim-stage only — the pre-auth prompt doesn't emit a breakdown.
    approved_breakdown = result.get("approved_breakdown") if is_claim_stage else None
    # denial_reason is emitted by BOTH prompts (DENIED/ENHANCEMENT_DENIED on
    # pre-auth, DENIED on claim).
    denial_reason = result.get("denial_reason")
    approved_breakdown = _sanitize_approved_breakdown(approved_breakdown)
    if denial_reason is not None and not isinstance(denial_reason, str):
        denial_reason = None
    # Coerce list elements to clean strings — the combined prompt sometimes
    # returns objects or descriptive strings; drop anything that isn't a name.
    if isinstance(documents_list, list):
        documents_list = [
            str(d).strip() for d in documents_list
            if isinstance(d, (str, int, float)) and str(d).strip()
        ]

    logger.info(f"OpenAI extracted: uhid={uhid}, claim_number={claim_number}, status={extracted_status}")

    # Validate against the right set; claim-stage doesn't allow ENHANCEMENT_*.
    valid_set = CLAIM_VALID_STATUSES if is_claim_stage else VALID_STATUSES
    if extracted_status not in valid_set:
        extracted_status = "UNKNOWN"

    # Second pass for ADR_NMI: the combined prompt is unreliable for arrays,
    # so call the focused extractor on the concatenated source text. Use its
    # result whenever it returns a non-None list (including the empty list,
    # which means "model is sure no docs are listed"). Falls through to the
    # combined-prompt output only when extract_documents fails (e.g. no API
    # key, OpenAI error).
    if extracted_status == "ADR_NMI":
        source_text = " ".join(
            part for part in (body, query_details, documents_requested) if part
        )
        focused = extract_documents(source_text)
        if focused is not None:
            documents_list = focused

    # 3. If not matched by thread_id, try uhid / claim_number / provider email
    if not claim_case:
        claim_case = _match_claim_case(db, uhid, claim_number, from_email)
    if not claim_case:
        logger.info(f"No awaiting-provider claim case found for email: {subject}")
        return

    # 4. Persist the received email with AI suggestions (no direct status update)
    _persist_email_record(
        db, claim_case, email_data, thread_id, extracted_status,
        ai_suggested_amount=approved_amount,
        ai_suggested_claim_number=claim_number,
        ai_summary=summary,
        ai_query_details=query_details,
        ai_documents_requested=documents_requested,
        ai_documents_list=documents_list,
        ai_approved_breakdown=approved_breakdown,
        ai_denial_reason=denial_reason,
    )

    db.commit()
    logger.info(
        f"Stored AI suggestion for ClaimCase #{claim_case.id} (uhid={claim_case.uhid}): "
        f"suggested_status={extracted_status}, claim_number={claim_number}, amount={approved_amount}"
    )

    # Fire a real-time push to any SSE subscribers for this hospital. This is
    # best-effort — wrapped in try/except so a hub error never breaks email
    # persistence (which has already committed by this point).
    try:
        from app.services.event_hub import event_hub  # local import to avoid circular
        event_hub.publish_threadsafe(
            claim_case.hospital_id,
            {
                "type": "email.received",
                "claim_case_id": str(claim_case.id),
                "subject": email_data.get("subject", ""),
                "from_email": email_data.get("from_email", ""),
            },
        )
    except Exception as _publish_err:  # pragma: no cover — defensive
        logger.warning(f"event_hub publish failed (non-fatal): {_publish_err}")


def _analyze_email_with_openai(subject: str, body: str, from_email: str) -> dict | None:
    """Use OpenAI to extract claim_number, status, and summary from email."""
    prompt = OPENAI_PROMPT.format(subject=subject, from_email=from_email, body=body[:10000])

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = response.choices[0].message.content.strip()

        # Clean markdown code blocks if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        return json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"OpenAI analysis failed: {e}")
        return None


# Claim-stage extractor. Sibling of `_analyze_email_with_openai` — same model,
# same JSON shape, but a prompt that's tuned to claim-settlement vocabulary
# instead of pre-auth vocabulary. Used only when the matched claim_case has
# `current_stage == 'CLAIM'`. The pre-auth extractor (above) is unaffected.

CLAIM_OPENAI_PROMPT = """
You are an expert in Indian health insurance CLAIM SETTLEMENT (not pre-auth).

The hospital has already been treated and discharged; this email is the
insurer's reply on the final cashless claim (post-treatment bill).

---
TASK
Read the email subject, body, and sender, and decide the CURRENT STATUS of
the claim settlement. Then extract status-specific evidence:
- APPROVED / PARTIALLY_APPROVED → per-line bill breakdown if quoted
- ADR_NMI → list of documents the insurer is asking for
- DENIED → the insurer's stated reason for rejection

Return ONE JSON object with EXACTLY these keys:
- status: one of APPROVED, PARTIALLY_APPROVED, DENIED, ADR_NMI, UNKNOWN
- uhid: string or null (patient's UHID — usually pasted from the original mail)
- claim_number: string or null (insurer's claim reference)
- approved_amount: number or null (total approved on this settlement, in INR)
- summary: short plain-text recap, ≤2 sentences
- query_details: string or null (for ADR_NMI; what the insurer is asking for)
- documents_requested: string or null (comma-separated; for ADR_NMI)
- documents_list: array of strings or null (each requested doc as one item)
- approved_breakdown: array of objects or null. Populate ONLY when status is
  APPROVED or PARTIALLY_APPROVED and the email quotes per-line figures.
  Each item must be: {{"label": "<head, e.g. Room rent>", "claimed": <number or null>, "approved": <number>}}.
  Plain numbers only — no commas / currency symbols. Skip the line entirely
  if you cannot parse the approved amount. Set null if no breakdown is given.
- denial_reason: string or null. Populate ONLY when status is DENIED — the
  insurer's stated reason in 1-2 short sentences (policy exclusion, eligibility,
  late submission, fraud, etc.). Null for every other status.

---
STATUS DEFINITIONS (claim stage — there is NO enhancement loop here)

- APPROVED: insurer settles the full claimed amount. Use this only when the
  email clearly states the entire bill is being paid.
- PARTIALLY_APPROVED: insurer settles less than the claimed amount; deductions
  may be itemised, quoted as a total, or expressed as a "settled amount".
- DENIED: insurer rejects the claim outright (policy exclusion, eligibility,
  fraud, late submission, etc.). No partial payment.
- ADR_NMI: insurer asks for additional documents or clarification before
  settling (e.g. "send original bills", "send discharge summary", "share
  investigation reports").
- UNKNOWN: the email is not clearly any of the above (acknowledgement,
  out-of-office reply, etc.).

Do NOT output ENHANCEMENT_APPROVED or ENHANCEMENT_DENIED — those belong to
the pre-auth stage and do not apply to claim settlement.

---
EXTRACTION RULES (strict)

approved_breakdown:
- Walk the email body for a settlement table or itemised list. Typical heads:
  "Room rent / nursing", "ICU", "Surgery / Operation theatre", "Anaesthesia",
  "Doctor / consultant fees", "Investigations / lab", "Pharmacy / medicines /
  consumables", "Implants", "Radiology", "Miscellaneous".
- Use the labels as written by the insurer. Normalise capitalisation but do
  not rename. If the email writes "OT Charges", emit "OT Charges".
- `claimed` is the hospital's billed amount for that line if quoted (often
  shown alongside the settled amount). Set null if not quoted.
- `approved` is the settled / payable amount for that line. Required.
- Skip "Deduction" / "Co-pay" / "Disallowed" rows — those are derived. Only
  emit positive payable rows.
- If only a single grand total is quoted (no per-line break-up), set
  approved_breakdown to null. Do NOT fabricate a single-row breakdown from
  the total.

documents_list (ADR_NMI):
- Each element a canonical document NAME as a string, never a description.
  Examples: "Discharge Summary", "Final Bill", "Pharmacy Bills",
  "Investigation Reports", "Operative Notes", "Indoor Case Papers", "Implant
  Sticker", "Death Summary", "MLC Report".
- Trim whitespace, merge near-duplicates, no objects, no descriptions.
- Return [] if no specific docs are listed.

denial_reason:
- 1-2 short sentences quoting the insurer's stated rationale. Do not editorialise.
- Examples: "Treatment falls under policy exclusion clause 4.2 (cosmetic
  procedures).", "Claim submitted after the 30-day window.", "Pre-existing
  disease not disclosed at policy inception.".

---
INPUTS

Email from: {from_email}
Email subject: {subject}

Email body:
{body}

Return ONLY valid JSON, no other text.
""".strip()


def _sanitize_approved_breakdown(raw) -> list[dict] | None:
    """Coerce AI-emitted approved_breakdown into the canonical
    [{label, claimed, approved}] shape. Drop rows that don't have a usable
    numeric approved value. Return None when nothing usable is present."""
    if not isinstance(raw, list) or not raw:
        return None
    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        approved = item.get("approved")
        try:
            approved_num = float(approved) if approved is not None else None
        except (TypeError, ValueError):
            approved_num = None
        if approved_num is None:
            continue
        claimed = item.get("claimed")
        try:
            claimed_num = float(claimed) if claimed is not None else None
        except (TypeError, ValueError):
            claimed_num = None
        cleaned.append({
            "label": label.strip(),
            "claimed": claimed_num,
            "approved": approved_num,
        })
    return cleaned or None


def _analyze_claim_email_with_openai(subject: str, body: str, from_email: str) -> dict | None:
    """Claim-stage sibling of `_analyze_email_with_openai`. Same model, same
    parsing path; different prompt and a narrower VALID_STATUSES set."""
    prompt = CLAIM_OPENAI_PROMPT.format(
        subject=subject, from_email=from_email, body=body[:10000],
    )
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        return json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"OpenAI claim analysis failed: {e}")
        return None


def _match_claim_case(
    db: Session, uhid: str | None, claim_number: str | None, from_email: str
) -> ClaimCase | None:
    """Match an email to a ClaimCase by uhid, claim_number, or provider email."""
    # 1. Try by uhid first (most reliable — extracted from "ID/TPA/Insured Id of the Patient")
    if uhid:
        claim_case = (
            db.query(ClaimCase)
            .filter(ClaimCase.uhid == uhid, ClaimCase.status.in_(AWAITING_PROVIDER_STATUSES))
            .first()
        )
        if claim_case:
            logger.info(f"Matched ClaimCase #{claim_case.id} by uhid={uhid}")
            return claim_case

    # 2. Try by claim_number
    if claim_number:
        claim_case = (
            db.query(ClaimCase)
            .filter(ClaimCase.claim_number == claim_number, ClaimCase.status.in_(AWAITING_PROVIDER_STATUSES))
            .first()
        )
        if claim_case:
            logger.info(f"Matched ClaimCase #{claim_case.id} by claim_number={claim_number}")
            return claim_case

    # 3. Fallback: try by provider email
    clean_email = from_email
    if "<" in from_email and ">" in from_email:
        clean_email = from_email.split("<")[1].split(">")[0]

    provider = (
        db.query(PolicyProviderConfig)
        .filter(PolicyProviderConfig.email == clean_email)
        .first()
    )
    if not provider:
        return None

    claim_cases = (
        db.query(ClaimCase)
        .filter(
            ClaimCase.policy_provider_id == provider.id,
            ClaimCase.status.in_(AWAITING_PROVIDER_STATUSES),
        )
        .all()
    )

    if len(claim_cases) == 1:
        logger.info(f"Matched ClaimCase #{claim_cases[0].id} by provider email={clean_email}")
        return claim_cases[0]
    elif len(claim_cases) > 1:
        logger.warning(
            f"Multiple awaiting-provider claim cases for provider {provider.name} ({clean_email}). "
            f"Skipping to avoid wrong update."
        )
        return None

    return None


def _fetch_unread_emails() -> list[dict]:
    """Fetch unread emails from inbox via IMAP."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(settings.EMAIL_ADDRESS, settings.EMAIL_APP_PASSWORD)
        mail.select("INBOX")

        _, message_numbers = mail.search(None, "UNSEEN")
        email_ids = message_numbers[0].split()

        if not email_ids or email_ids == [b""]:
            mail.logout()
            return []

        emails = []
        for eid in email_ids:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw_email)

            subject = _decode_header_value(msg["Subject"])
            from_email = _decode_header_value(msg["From"])
            date = msg["Date"] or ""
            body = _extract_body(msg)
            pdf_text = _extract_pdf_text(msg)

            # Combine body + PDF text for OpenAI analysis
            full_content = body
            if pdf_text:
                full_content = f"{body}\n\n--- Attached PDF Content ---\n{pdf_text}"

            raw_body = body
            message_id = msg.get("Message-ID", "")
            attachments = _extract_attachments(msg)

            emails.append({
                "id": eid.decode(),
                "from_email": from_email,
                "subject": subject,
                "date": date,
                "body": full_content,
                "raw_body": raw_body,
                "message_id": message_id.strip() if message_id else "",
                "attachments": attachments,
            })

        mail.logout()
        return emails

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
        return []


def _decode_header_value(value: str | None) -> str:
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


def _extract_pdf_text(msg) -> str:
    """Extract text from all PDF attachments in the email."""
    pdf_texts = []
    if not msg.is_multipart():
        return ""

    for part in msg.walk():
        content_type = part.get_content_type()
        filename = part.get_filename()

        if content_type == "application/pdf" or (filename and filename.lower().endswith(".pdf")):
            payload = part.get_payload(decode=True)
            if payload:
                try:
                    reader = PdfReader(io.BytesIO(payload))
                    text = ""
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    if text.strip():
                        pdf_texts.append(f"[{filename or 'attachment.pdf'}]\n{text.strip()}")
                        logger.info(f"Extracted text from PDF: {filename}")
                except Exception as e:
                    logger.warning(f"Could not extract text from PDF {filename}: {e}")

    return "\n\n".join(pdf_texts)


def _extract_attachments(msg) -> list[dict]:
    """Extract all attachments as {filename, content_type, data} dicts."""
    attachments = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        content_disposition = part.get("Content-Disposition", "")
        if "attachment" in content_disposition:
            filename = part.get_filename() or "unnamed_attachment"
            filename = _decode_header_value(filename)
            payload = part.get_payload(decode=True)
            if payload:
                attachments.append({
                    "filename": filename,
                    "content_type": part.get_content_type(),
                    "data": payload,
                })
    return attachments


def _parse_email_date(date_str: str):
    """Parse email date header to datetime."""
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


STATUS_TO_EMAIL_TYPE = {
    "APPROVED": "APPROVAL",
    "PARTIALLY_APPROVED": "PARTIAL_APPROVAL",
    "DENIED": "DENIAL",
    "ENHANCEMENT_APPROVED": "ENHANCEMENT_APPROVAL",
    "ENHANCEMENT_DENIED": "ENHANCEMENT_DENIAL",
    "ADR_NMI": "ADR_NMI",
}

# Claims that are waiting on a provider response — inbound emails can only
# match against cases in one of these workflow states. Sourced from the
# central definition in claim_case_controller so claim-stage statuses
# (CLAIM_SUBMITTED / CLAIM_ADR_SUBMITTED / CLAIM_RECONSIDER) are picked up
# automatically without drift.
from app.controllers.claim_case_controller import (
    AWAITING_PROVIDER_STATUSES as _AWAITING_SET,
    CLAIM_STATUS_TO_EMAIL_TYPE,
)
AWAITING_PROVIDER_STATUSES = tuple(_AWAITING_SET)


def _persist_email_record(
    db: Session, claim_case: ClaimCase, email_data: dict, thread_id: str | None,
    extracted_status: str | None = None, ai_suggested_amount=None,
    ai_suggested_claim_number: str | None = None, ai_summary: str | None = None,
    ai_query_details: str | None = None, ai_documents_requested: str | None = None,
    ai_documents_list: list[str] | None = None,
    ai_approved_breakdown: list[dict] | None = None,
    ai_denial_reason: str | None = None,
):
    """Persist a received email and its attachments with AI suggestions to the database."""
    message_id = email_data.get("message_id", "")

    # Dedup by message_id
    if message_id:
        existing = db.query(ClaimCaseEmail).filter(
            ClaimCaseEmail.message_id == message_id
        ).first()
        if existing:
            logger.info(f"Email already stored (message_id={message_id}), skipping persistence")
            return

    # Stage-aware email_type. On a claim-stage case, even if the pre-auth
    # extractor ran (uhid/claim_number fallback path), we map the status to
    # the CLAIM_* email_type so the timeline reads correctly. Coerce dead
    # enhancement statuses on claim stage — there is no enhancement loop.
    if claim_case.current_stage == "CLAIM":
        status_for_map = extracted_status
        if status_for_map == "ENHANCEMENT_APPROVED":
            status_for_map = "APPROVED"
        elif status_for_map == "ENHANCEMENT_DENIED":
            status_for_map = "DENIED"
        email_type = CLAIM_STATUS_TO_EMAIL_TYPE.get(status_for_map) if status_for_map else None
    else:
        email_type = STATUS_TO_EMAIL_TYPE.get(extracted_status) if extracted_status else None

    email_record = ClaimCaseEmail(
        claim_case_id=claim_case.id,
        direction="RECEIVED",
        from_email=email_data.get("from_email", ""),
        to_email=settings.EMAIL_ADDRESS,
        subject=email_data.get("subject", ""),
        body=email_data.get("raw_body", email_data.get("body", "")),
        message_id=message_id or None,
        thread_id=thread_id,
        email_type=email_type,
        email_date=_parse_email_date(email_data.get("date", "")),
        ai_suggested_status=extracted_status,
        ai_suggested_amount=ai_suggested_amount,
        ai_suggested_claim_number=ai_suggested_claim_number,
        ai_summary=ai_summary,
        ai_query_details=ai_query_details,
        ai_documents_requested=ai_documents_requested,
        ai_documents_list=ai_documents_list,
        ai_approved_breakdown=ai_approved_breakdown,
        ai_denial_reason=ai_denial_reason,
        validation_status="PENDING",
    )
    db.add(email_record)
    db.flush()

    for att in email_data.get("attachments", []):
        stored_filename, file_path = save_attachment(
            claim_case.id, att["data"], att["filename"]
        )
        db.add(ClaimCaseEmailAttachment(
            email_id=email_record.id,
            claim_case_id=claim_case.id,
            original_filename=att["filename"],
            stored_filename=stored_filename,
            file_path=file_path,
            content_type=att["content_type"],
            file_size=len(att["data"]),
        ))

    logger.info(
        f"Persisted received email for ClaimCase #{claim_case.id} "
        f"with {len(email_data.get('attachments', []))} attachment(s)"
    )


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

"""seed Part-D form template

Revision ID: e7a2d9c4f150
Revises: d52e3c8a417b
Create Date: 2026-05-08 13:18:38.733531

Inserts the Cashless Authorization Letter (Part-D) HTML template for the
SBI-provider policy provider. Idempotent: skips if the SBI-provider row is
absent (e.g. fresh DB without seed data), or if a (name, version, form_type)
row already exists.

The template body uses Mustache-style {{placeholder}} markers; the frontend
fills them in. See `feedback_form_terminology.md` in the project memory for
why this is named PART_D and not FORM_C.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7a2d9c4f150'
down_revision: Union[str, None] = 'd52e3c8a417b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROVIDER_SLUG = "SBI-provider"
TEMPLATE_NAME = "part-d-default"
TEMPLATE_VERSION = 1
TEMPLATE_FORM_TYPE = "PART_D"


PART_D_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Cashless Authorization Letter (Part-D)</title>
<style>
  @page { size: A4; margin: 12mm; }
  * { box-sizing: border-box; }
  body { font-family: "Times New Roman", Times, serif; color: #000; font-size: 11px; line-height: 1.35; margin: 0; }
  .page { border: 1px solid #000; padding: 10px; margin: 0 0 12px; }
  .title { text-align: center; font-weight: bold; text-decoration: underline; font-size: 14px; }
  .subtitle { text-align: center; font-weight: bold; font-size: 13px; margin-bottom: 8px; }
  table { border-collapse: collapse; width: 100%; }
  td, th { padding: 4px 6px; vertical-align: top; }
  table.bordered td, table.bordered th { border: 1px solid #000; }
  .right { text-align: right; }
  .section-title { font-weight: bold; text-decoration: underline; margin: 10px 0 4px; }
  .auth-table th { background: #e9e9e9; text-align: left; }
  .summary-label { width: 50%; font-weight: bold; padding-left: 60px; }
  .terms ol { padding-left: 22px; }
  .terms li { margin-bottom: 6px; }
  .label-col { width: 28%; }
</style>
</head>
<body>

<div class="page">
  <div class="title">Cashless Authorization Letter</div>
  <div class="subtitle">(Part-D)</div>

  <table style="margin-bottom: 6px;">
    <tr>
      <td><strong>Claim Number:</strong> {{claim_number}} ( Pleaes quote this number for all further correspondence )</td>
      <td class="right"><strong>Date:</strong> {{date}}</td>
    </tr>
  </table>

  <table class="bordered" style="margin-bottom: 8px;">
    <tr>
      <td class="label-col">Hospital Name</td>
      <td>: {{hospital_name}}</td>
      <td class="label-col">Name of the Insurance Company</td>
      <td>: {{insurance_company}}</td>
    </tr>
    <tr>
      <td>Address</td>
      <td>: {{hospital_address}}</td>
      <td>Name of TPA</td>
      <td>: {{tpa_name}}</td>
    </tr>
    <tr>
      <td></td>
      <td></td>
      <td>Proposer Name</td>
      <td>: {{proposer_name}}</td>
    </tr>
    <tr>
      <td></td>
      <td></td>
      <td>Patient's Member ID/TPA/Insurer Id of the Patient:</td>
      <td>: {{patient_member_id}}</td>
    </tr>
    <tr>
      <td>Rohini ID</td>
      <td>: {{rohini_id}}</td>
      <td>Relation with Proposer</td>
      <td>: {{relation_with_proposer}}</td>
    </tr>
  </table>

  <p>Dear Sir / Madam,</p>
  <p>This has reference to the pre-authorization request submitted on {{preauth_request_date}}. We hereby authorize cashless facility as per details mentioned below:</p>

  <table class="bordered" style="margin-bottom: 8px;">
    <tr>
      <td class="label-col">Patient Name</td>
      <td>: {{patient_name}}</td>
      <td>Age</td>
      <td>: {{patient_age}}</td>
      <td>Gender</td>
      <td>: {{patient_gender}}</td>
    </tr>
    <tr>
      <td>Policy Number</td>
      <td colspan="3">: {{policy_number}}</td>
      <td>Expected Date of Admission</td>
      <td>: {{expected_admission_date}}</td>
    </tr>
    <tr>
      <td>Policy Period</td>
      <td colspan="3">: {{policy_period_from}} To {{policy_period_to}}</td>
      <td>Expected Date of Discharge</td>
      <td>: {{expected_discharge_date}}</td>
    </tr>
    <tr>
      <td>Room category</td>
      <td colspan="3">: {{room_category}}</td>
      <td>Estimated length of stay</td>
      <td>: {{estimated_length_of_stay}}</td>
    </tr>
    <tr>
      <td>Eligible Room Category as per T&amp;C of Policy Contract</td>
      <td colspan="5">: {{eligible_room_category}}</td>
    </tr>
    <tr>
      <td>Provisional Diagnosis</td>
      <td colspan="3">: {{provisional_diagnosis}}</td>
      <td>Proposed line of treatment</td>
      <td>: {{proposed_line_of_treatment}}</td>
    </tr>
  </table>

  <div class="section-title">Authorization Details :-</div>
  <table class="bordered auth-table" style="margin-bottom: 8px;">
    <thead>
      <tr><th>Date &amp; Time</th><th>Reference Number</th><th>Amount</th><th>Status</th></tr>
    </thead>
    <tbody>
      {{#authorization_details}}
      <tr><td>{{date_time}}</td><td>{{reference_number}}</td><td>{{amount}}</td><td>{{status}}</td></tr>
      {{/authorization_details}}
    </tbody>
  </table>

  <p><strong>Total Authorized amount:-</strong> Rs. {{total_authorized_amount_in_words}}( In Words )</p>

  <div class="section-title">Authorization Remarks :</div>
  <p>{{authorization_remarks}}</p>
</div>

<div class="page">
  <div class="section-title">Hospital Agreed Tariff :-</div>
  <ol type="I" style="margin: 0 0 6px 16px;">
    <li><strong>Package Case</strong></li>
    <li><strong>Non-package Case</strong>
      <ol type="i" style="margin: 4px 0;">
        <li>ROOM RENT/DAY : {{room_rent_per_day}}</li>
        <li>ICU RENT/DAY : {{icu_rent_per_day}}</li>
        <li>NURSING CHARGES/DAY : {{nursing_charges_per_day}}</li>
        <li>CONSULTANT VISIT CHARGES/DAY : {{consultant_visit_charges_per_day}}</li>
        <li>SURGEON FEE/OT/ANESTHETIST : {{surgeon_fee_ot_anesthetist}}</li>
        <li>OTHERS (specify) : {{others_specify}}</li>
      </ol>
    </li>
  </ol>

  <div class="section-title">Authorization Summary :-</div>
  <table style="margin: 0 0 8px 0;">
    <tr><td class="summary-label">Total Bill Amount</td><td>:(INR) {{total_bill_amount}}</td></tr>
    <tr><td class="summary-label">Deductions Detail</td><td>:(INR) {{deductions_detail}}</td></tr>
    <tr><td class="summary-label">Discount</td><td>:(INR) {{discount}}</td></tr>
    <tr><td class="summary-label">Co-Pay</td><td>:(INR) {{co_pay}}</td></tr>
    <tr><td class="summary-label">Deductibles</td><td>:(INR) {{deductibles}}</td></tr>
    <tr><td class="summary-label">Total Authorised Amount</td><td>:(INR) {{total_authorised_amount}}</td></tr>
    <tr><td class="summary-label">Amount to be paid by Insured</td><td>:(INR) {{amount_to_be_paid_by_insured}}</td></tr>
  </table>

  <div class="section-title">Total Deduction Details :-</div>
  <table class="bordered">
    <thead>
      <tr>
        <th>S. no.</th><th>Description</th><th>Bill Amount</th>
        <th>Deducted Amount</th><th>Admissible Amount</th><th>Deduction Reason</th>
      </tr>
    </thead>
    <tbody>
      {{#deduction_details}}
      <tr>
        <td>{{s_no}}</td><td>{{description}}</td><td>{{bill_amount}}</td>
        <td>{{deducted_amount}}</td><td>{{admissible_amount}}</td><td>{{deduction_reason}}</td>
      </tr>
      {{/deduction_details}}
    </tbody>
  </table>
</div>

<div class="page terms">
  <div class="section-title">Terms and Conditions of Authorization :-</div>
  <ol>
    <li>Cashless Authorization letter issued on the basis of information provided in Pre-Authorization form. In case misrepresentation/concealment of the facts, any material difference/deviation/discrepancy in information is observed in discharge summary/IPD records then cashless authorization shall stand null &amp; void. At any point of claim processing Insurer or TPA reserves right to raise queries for any other document to ascertain admissibility of claim.</li>
    <li>KYC (Know your customer) details of proposer/employee/Beneficiary are mandatory for claim payout above Rs 1 lakh.</li>
    <li>Network provider shall not collect any additional amount from the individual in excess of Agreed Package Rates except costs towards non-admissible amounts (including additional charges due to opting higher room rent than eligibility/choosing separate line of treatment which is not envisaged/considered in package).</li>
    <li>Network provider shall not make any recovery from the deposit amount collected from the Insured except for costs towards non-admissible amounts (including additional charges due to opting higher room rent than eligibility/choosing separate line of treatment which is not envisaged/considered in package).</li>
    <li>In the event of unauthorized recovery of any additional amount from the Insured in excess of Agreed Package Rates, the authorized TPA / Insurance Company reserves the right to recover the same or get the same refunded to the policyholder from the Network Provider and/or take necessary action, as provided under the MoU.</li>
    <li>Where a treatment/procedure is to be carried out by a doctor/surgeon of insured's choice (not empaneled with the hospital), Network Provider may give treatment after obtaining specific consent of policyholder.</li>
    <li>Differential Costs borne by policyholder may be reimbursed by insurers subject to the terms and conditions of the policy.</li>
  </ol>

  <div class="section-title">DOCUMENTS TO BE PROVIDED BY THE HOSPITAL IN SUPPORT OF THE CLAIM</div>
  <ol>
    <li>Detailed Discharge Summary and all Bills from the hospital</li>
    <li>Cash Memos from the Hospitals / Chemists supported by proper prescription.</li>
    <li>Diagnostic Test Reports and Receipts supported by note from the attending Medical Practitioner / Surgeon recommending such Diagnostic supported by note from the attending Medical Practitioner / Surgeon recommending such diagnostic tests.</li>
    <li>Surgeon's Certificate stating nature of operation performed and Surgeon's Bill and Receipt.</li>
    <li>Certificates from attending Medical Practitioner / Surgeon giving patient's condition and advice on discharge.</li>
  </ol>

  <p><strong>Name of the Product</strong> {{product_name}} <strong>and UIN No :-</strong> {{product_uin}} Important Policy terms &amp; conditions ( sub-limits/co-pay/deductible etc) {{policy_terms_summary}}</p>

  <p style="margin-top: 16px;"><strong>Authorized signatory :</strong> {{authorized_signatory}}</p>
  <p><strong>(Insurer/TPA)</strong> {{insurer_or_tpa}}</p>
  <p><strong>Address :</strong></p>
  <p>{{insurer_address}}<br/>
  Phone: {{insurer_phone}}; Fax: {{insurer_fax}}</p>
</div>

</body>
</html>
"""


def upgrade() -> None:
    conn = op.get_bind()
    provider_id = conn.execute(
        sa.text(
            "SELECT id FROM policy_provider_configs WHERE provider_id = :slug"
        ),
        {"slug": PROVIDER_SLUG},
    ).scalar()

    if provider_id is None:
        # Provider seed not present in this environment; skip silently so the
        # migration is safe to run anywhere.
        return

    existing = conn.execute(
        sa.text(
            "SELECT id FROM form_templates "
            "WHERE name = :name AND version = :version AND form_type = :ft"
        ),
        {"name": TEMPLATE_NAME, "version": TEMPLATE_VERSION, "ft": TEMPLATE_FORM_TYPE},
    ).scalar()
    if existing is not None:
        return

    conn.execute(
        sa.text(
            "INSERT INTO form_templates "
            "(name, version, form_type, policy_provider_id, html_content, is_active) "
            "VALUES (:name, :version, :ft, :pid, :html, true)"
        ),
        {
            "name": TEMPLATE_NAME,
            "version": TEMPLATE_VERSION,
            "ft": TEMPLATE_FORM_TYPE,
            "pid": provider_id,
            "html": PART_D_HTML,
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM form_templates "
            "WHERE name = :name AND version = :version AND form_type = :ft"
        ),
        {"name": TEMPLATE_NAME, "version": TEMPLATE_VERSION, "ft": TEMPLATE_FORM_TYPE},
    )

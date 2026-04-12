from fastapi import APIRouter, Request

router = APIRouter(prefix="/mock", tags=["Mock"])

MOCK_RESPONSE = {
    # Patient / Insured Details
    "insured_card_id": "IC-2024-00987654",
    "corporate_name": "Tata Consultancy Services",
    "employee_id": "EMP-TCS-44210",
    "relative_contact_number": "+91-9123456789",
    "has_other_insurance": True,
    "other_insurance_company": "HDFC ERGO Health Insurance",
    "other_insurance_details": "Policy No: HE-2024-556677, Sum Insured: 5,00,000",
    "has_family_physician": True,
    "family_physician_name": "Dr. Ramesh Gupta",
    "family_physician_contact": "+91-9988776655",
    "occupation": "Software Engineer",

    # Treating Doctor
    "doctor_contact": "+91-9876543210",
    "past_history": "Known case of Type 2 Diabetes Mellitus for 5 years, on Metformin 500mg BD",
    "provisional_diagnosis": "Acute Appendicitis with Localized Peritonitis",

    # Treatment Plan
    "medical_management": False,
    "surgical_management": True,
    "intensive_care": False,
    "investigation": True,
    "non_allopathic": False,

    # Treatment Details
    "illness_description": "Acute appendicitis with peritonitis requiring emergency laparoscopic appendectomy",
    "critical_findings": "Elevated WBC count (18,000/mcL), CT scan shows inflamed appendix with surrounding fluid collection",
    "treatment_details": "Laparoscopic appendectomy under general anaesthesia with post-operative IV antibiotics",
    "drug_route": "IV Ceftriaxone 1g BD, IV Metronidazole 500mg TDS, IV Paracetamol 1g PRN",
    "surgery_name": "Laparoscopic Appendectomy",
    "surgery_icd_code": "0DTJ4ZZ",
    "other_treatment": "Post-operative physiotherapy and respiratory exercises",
    "injury_cause": "Non-traumatic, spontaneous onset",
    "duration_days": 5,
    "icd10_code": "K35.80",

    # Accident Details
    "is_rta": False,
    "injury_date": None,
    "reported_to_police": False,
    "fir_number": None,
    "substance_abuse": False,
    "test_conducted": "Blood panel, Urine analysis, CT Abdomen",

    # Maternity
    "expected_delivery_date": None,

    # Hospitalization
    "admission_date": "2026-04-10",
    "admission_time": "14:30",
    "is_emergency": True,
    "expected_days": 5,
    "icu_days": 0,
    "room_type": "Semi-Private",

    # Chronic Conditions
    "diabetes": True,
    "heart_disease": False,
    "hypertension": False,
    "hyperlipidemia": False,
    "osteoarthritis": False,
    "asthma_copd": False,
    "cancer": False,
    "alcohol_drug_abuse": False,
    "hiv_std": False,
    "other": None,

    # Cost Estimates
    "room_rent": 12000.00,
    "investigation_cost": 8500.00,
    "icu_charges": 0.00,
    "ot_charges": 35000.00,
    "professional_fees": 25000.00,
    "medicines_cost": 15000.00,
    "other_expenses": 5000.00,
    "package_charges": 0.00,
    "total_cost": 100500.00,
}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def mock_endpoint(request: Request):
    return MOCK_RESPONSE

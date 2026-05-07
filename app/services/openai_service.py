import json

from openai import AsyncOpenAI, OpenAIError
from fastapi import HTTPException, status

from app.core.config import settings

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def summarize_with_openai(rendered_prompt: str) -> str:
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": rendered_prompt},
            ],
        )
        return response.choices[0].message.content
    except OpenAIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI API error: {str(e)}",
        )


# JSON schema for the /run-policy summary response. The caller's prompt
# (stored in the DB) decides HOW each field is populated — this schema only
# fixes the SHAPE the model must emit.
POLICY_SUMMARY_SCHEMA = {
    "name": "policy_summary",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "policy_number", "chronic_conditions", "cost_estimates"],
        "properties": {
            "summary": {
                "type": "string",
                "description": "Plain-language summary of the policy.",
            },
            "policy_number": {
                "type": ["string", "null"],
                "description": "Policy number extracted from the file (e.g. 'POL-2024-12345'). Null if no policy number is present in the document.",
            },
            "chronic_conditions": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "diabetes",
                    "heart_disease",
                    "hypertension",
                    "hyperlipidemia",
                    "osteoarthritis",
                    "asthma_copd",
                    "cancer",
                    "alcohol_drug_abuse",
                    "hiv_std",
                    "other",
                ],
                "properties": {
                    "diabetes": {"type": "string"},
                    "heart_disease": {"type": "string"},
                    "hypertension": {"type": "string"},
                    "hyperlipidemia": {"type": "string"},
                    "osteoarthritis": {"type": "string"},
                    "asthma_copd": {"type": "string"},
                    "cancer": {"type": "string"},
                    "alcohol_drug_abuse": {"type": "string"},
                    "hiv_std": {"type": "string"},
                    "other": {"type": ["string", "null"]},
                },
            },
            "cost_estimates": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "room_rent",
                    "investigation_cost",
                    "icu_charges",
                    "ot_charges",
                    "professional_fees",
                    "medicines_cost",
                    "other_expenses",
                    "package_charges",
                    "total_cost",
                ],
                "properties": {
                    "room_rent": {"type": ["string", "null"]},
                    "investigation_cost": {"type": ["string", "null"]},
                    "icu_charges": {"type": ["string", "null"]},
                    "ot_charges": {"type": ["string", "null"]},
                    "professional_fees": {"type": ["string", "null"]},
                    "medicines_cost": {"type": ["string", "null"]},
                    "other_expenses": {"type": ["string", "null"]},
                    "package_charges": {"type": ["string", "null"]},
                    "total_cost": {"type": ["string", "null"]},
                },
            },
        },
    },
}


async def summarize_policy_with_openai(rendered_prompt: str) -> dict:
    """Call OpenAI with a strict JSON schema so the response always contains
    `summary` and `chronic_conditions`. The prompt itself (sourced from the
    SummaryPromptTemplate in the DB) should describe the rules for populating
    each field.
    """
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": rendered_prompt}],
            response_format={"type": "json_schema", "json_schema": POLICY_SUMMARY_SCHEMA},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    except OpenAIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI API error: {str(e)}",
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI returned invalid JSON: {str(e)}",
        )

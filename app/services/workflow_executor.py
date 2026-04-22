import io
import json
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from PyPDF2 import PdfReader
from sqlalchemy.orm import Session

from app.models.hospital_config import HospitalConfig
from app.models.hospital_prompt import HospitalPrompt
from app.models.summary_prompt_template import SummaryPromptTemplate
from app.services.openai_service import summarize_with_openai, summarize_policy_with_openai
from app.utils.template import render_template, extract_fields


def _get_summary_prompt_text(db: Session, key: str, default_prompt: str) -> str:
    prompt = (
        db.query(SummaryPromptTemplate)
        .filter(SummaryPromptTemplate.key == key)
        .first()
    )
    if not prompt:
        return default_prompt
    return prompt.prompt_text


def _extract_file_text(
    file_bytes: bytes | None,
    file_name: str | None,
    file_content_type: str | None,
    max_chars: int = 12000,
) -> str:
    if not file_bytes:
        return ""

    is_pdf = (
        (file_content_type or "").lower() == "application/pdf"
        or ((file_name or "").lower().endswith(".pdf"))
    )

    try:
        if is_pdf:
            reader = PdfReader(io.BytesIO(file_bytes))
            extracted_parts: list[str] = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    extracted_parts.append(page_text)
            text = "\n".join(extracted_parts).strip()
        else:
            text = file_bytes.decode("utf-8", errors="replace").strip()
    except Exception:
        text = ""

    if not text:
        return ""
    return text[:max_chars]


async def call_api(
    method: str, url: str, headers: dict, body: dict | None
) -> dict[str, Any]:
    """Make an async HTTP call and return the JSON response."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        if method.upper() == "GET":
            resp = await client.get(url, headers=headers)
        elif method.upper() == "POST":
            resp = await client.post(url, headers=headers, json=body)
        elif method.upper() == "PUT":
            resp = await client.put(url, headers=headers, json=body)
        elif method.upper() == "PATCH":
            resp = await client.patch(url, headers=headers, json=body)
        elif method.upper() == "DELETE":
            resp = await client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        resp.raise_for_status()
        return resp.json()


async def _execute_auth_step(auth_config: dict, context: dict) -> dict:
    """Execute the optional auth step and return debug info."""
    url = render_template(auth_config["url"], context)
    method = auth_config.get("method", "POST")
    headers = render_template(auth_config.get("headers", {}), context)
    body = render_template(auth_config.get("body", {}), context)

    response_data = await call_api(method, url, headers, body)
    print(f"[AUTH] url={url} method={method}")
    print(f"[AUTH] response={response_data}")

    mapping = auth_config.get("response_mapping", {})
    extracted = extract_fields(response_data, mapping)
    print(f"[AUTH] extracted={extracted}")
    context.update(extracted)
    print(f"[AUTH] context={context}")

    return {
        "step": "auth",
        "resolved_url": url,
        "resolved_headers": headers,
        "resolved_body": body,
        "response": response_data,
    }


async def _execute_step(step_config: dict, context: dict) -> dict:
    """Execute a single workflow step and return debug info."""
    url = render_template(step_config["url"], context)
    method = step_config.get("method", "GET")
    headers = render_template(step_config.get("headers", {}), context)
    body = render_template(step_config.get("body_template", {}), context)

    step_name = step_config["step"]
    print(f"[STEP:{step_name}] url={url} method={method}")
    print(f"[STEP:{step_name}] headers={headers}")
    print(f"[STEP:{step_name}] body={body}")

    response_data = await call_api(method, url, headers, body)
    print(f"[STEP:{step_name}] response={response_data}")

    mapping = step_config.get("response_mapping", {})
    extracted = extract_fields(response_data, mapping)
    print(f"[STEP:{step_name}] extracted={extracted}")
    context.update(extracted)
    print(f"[STEP:{step_name}] context={context}")

    return {
        "step": step_name,
        "resolved_url": url,
        "resolved_headers": headers,
        "resolved_body": body,
        "response": response_data,
    }


async def execute_workflow_from_config(
    config: dict[str, Any], input_data: dict[str, Any]
) -> dict[str, Any]:
    """Execute a workflow given a config dict and input data. Reusable for any workflow type."""
    required_fields = config.get("required_fields", [])
    print(f"[WORKFLOW] input_data={input_data}")

    context: dict[str, Any] = input_data.copy()
    steps_debug: list[dict] = []

    auth_config = config.get("auth")
    if auth_config:
        try:
            debug = await _execute_auth_step(auth_config, context)
            steps_debug.append(debug)
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Auth step failed: {e.response.status_code} - {e.response.text}",
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Auth step connection error: {str(e)}",
            )

    for step_config in config.get("steps", []):
        step_name = step_config.get("step", "unknown")
        try:
            debug = await _execute_step(step_config, context)
            steps_debug.append(debug)
        except httpx.HTTPStatusError as e:
            print(f"[STEP:{step_name}] FAILED: {e.response.status_code} - {e.response.text}")
            steps_debug.append({
                "step": step_name,
                "error": f"{e.response.status_code} - {e.response.text}",
            })
            if step_config.get("stop_on_failure", True):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Step '{step_name}' failed: {e.response.status_code} - {e.response.text}",
                )
        except httpx.RequestError as e:
            print(f"[STEP:{step_name}] CONNECTION ERROR: {str(e)}")
            steps_debug.append({
                "step": step_name,
                "error": f"Connection error: {str(e)}",
            })
            if step_config.get("stop_on_failure", True):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Step '{step_name}' connection error: {str(e)}",
                )

    print(f"[WORKFLOW] final context={context}")

    if required_fields:
        output_data = {k: context.get(k) for k in required_fields}
    else:
        output_data = context

    return {
        "data": output_data,
        "steps_debug": steps_debug,
    }


async def execute_policy_workflow_with_summary(
    db: Session,
    config: dict[str, Any],
    input_data: dict[str, Any],
    file_name: str | None = None,
    file_content_type: str | None = None,
    file_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Execute provider workflow (when policy_id is present) and summarize via OpenAI."""
    policy_id = input_data.get("policy_id")
    if policy_id:
        result = await execute_workflow_from_config(config, input_data)
        response_data = result["data"]
        steps_debug = result["steps_debug"]
    else:
        response_data = {}
        steps_debug = []

    file_text = _extract_file_text(file_bytes, file_name, file_content_type)
    print(
        f"[POLICY] file_name={file_name!r} content_type={file_content_type!r} "
        f"raw_bytes={len(file_bytes) if file_bytes else 0} "
        f"extracted_chars={len(file_text)}"
    )
    if file_text:
        print(f"[POLICY] file_text preview: {file_text[:400]!r}")

    if policy_id:
        policy_key = "policy-summary"
        default_prompt = (
            "Summarize this policy workflow response in plain language. "
            "Keep it concise and include key policy details, approval/rejection indicators, "
            "and notable amounts or dates if present.\n\n"
            "Response JSON:\n{response_json}\n\n"
            "Attached file context:\n{file_context}"
        )
    else:
        policy_key = "policy-summary-file-only"
        default_prompt = (
            "Summarize the attached policy document context in plain language. "
            "Keep it concise and include important coverage details, restrictions, waiting periods, "
            "and notable amounts or dates if present.\n\n"
            "Attached file context:\n{file_context}"
        )

    prompt_template = _get_summary_prompt_text(db, policy_key, default_prompt)
    prompt = (
        prompt_template
        .replace(
            "{response_json}",
            json.dumps(response_data, ensure_ascii=False, default=str, indent=2),
        )
        .replace("{file_context}", file_text or "No file context provided")
    )

    structured = await summarize_policy_with_openai(prompt)
    return {
        "summary": structured.get("summary", ""),
        "data": response_data,
        "steps_debug": steps_debug,
        "chronic_conditions": structured.get("chronic_conditions"),
        "cost_estimates": structured.get("cost_estimates"),
    }


async def execute_workflow(
    db: Session, hospital_id: UUID, input_data: dict[str, Any]
) -> dict[str, Any]:
    """Load hospital config, execute workflow, render prompt, and summarize via OpenAI."""
    config_row = (
        db.query(HospitalConfig)
        .filter(HospitalConfig.hospital_id == hospital_id)
        .first()
    )
    if not config_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No config found for this hospital",
        )

    print(f"[WORKFLOW] hospital_id={hospital_id}")
    global_vars = config_row.global_variables or {}
    merged_input = {**global_vars, **input_data}
    print(f"[WORKFLOW] global_variables={global_vars}")
    result = await execute_workflow_from_config(config_row.config, merged_input)

    # Fetch hospital prompt and replace variables with workflow output
    prompt_row = (
        db.query(HospitalPrompt)
        .filter(HospitalPrompt.hospital_id == hospital_id)
        .first()
    )
    if not prompt_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No prompt found for this hospital",
        )

    rendered_prompt = prompt_row.prompt_text

    # Build response-mapping-only data (exclude global vars and input)
    skip_keys = set(global_vars.keys()) | set(input_data.keys())
    response_mapping_data = {
        k: v for k, v in result["data"].items() if k not in skip_keys
    }

    # Replace {pre_auth_form_data} with all response mapping fields
    if "{pre_auth_form_data}" in rendered_prompt:
        form_data_str = "\n".join(
            f"{key}: {value}" for key, value in response_mapping_data.items()
        )
        rendered_prompt = rendered_prompt.replace("{pre_auth_form_data}", form_data_str)

    for key, value in result["data"].items():
        rendered_prompt = rendered_prompt.replace(
            "{" + key + "}", str(value) if value is not None else ""
        )
    print(f"[WORKFLOW] rendered_prompt={rendered_prompt}")

    # Send to OpenAI for summarization
    summary = await summarize_with_openai(rendered_prompt)
    print(f"[WORKFLOW] summary={summary}")

    return {"summary": summary, "data": result["data"]}


async def summarize_patient_policy_context(
    db: Session,
    patient: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    default_prompt = (
        "Create a concise medical insurance context summary from the provided patient and policy data. "
        "Highlight patient identity details, admission/treatment context if present, policy coverage/restrictions, "
        "and any important gaps or missing fields.\n\n"
        "Patient JSON:\n{patient_json}\n\n"
        "Policy JSON:\n{policy_json}"
    )
    prompt_template = _get_summary_prompt_text(db, "/summarize-context", default_prompt)
    prompt = (
        prompt_template
        .replace("{patient_json}", json.dumps(patient, ensure_ascii=False, default=str, indent=2))
        .replace("{policy_json}", json.dumps(policy, ensure_ascii=False, default=str, indent=2))
    )
    summary = await summarize_with_openai(prompt)
    return {"summary": summary}

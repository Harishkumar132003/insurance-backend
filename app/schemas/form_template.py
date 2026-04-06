from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator


SUPPORTED_FIELD_TYPES = {"text", "textarea", "number", "date", "radio", "checkbox"}


class FormTemplateCreate(BaseModel):
    name: str
    version: int
    schema_json: dict[str, Any]

    @model_validator(mode="after")
    def validate_schema_structure(self):
        schema = self.schema_json

        if "sections" not in schema or not isinstance(schema["sections"], list):
            raise ValueError("schema_json must contain a 'sections' list")

        for i, section in enumerate(schema["sections"]):
            if "fields" not in section or not isinstance(section["fields"], list):
                raise ValueError(f"Section at index {i} must contain a 'fields' list")

            for j, field in enumerate(section["fields"]):
                if "key" not in field:
                    raise ValueError(f"Field at index {j} in section '{section.get('name', i)}' must have a 'key'")
                if "type" not in field:
                    raise ValueError(f"Field '{field['key']}' must have a 'type'")
                if field["type"] not in SUPPORTED_FIELD_TYPES:
                    raise ValueError(
                        f"Field '{field['key']}' has unsupported type '{field['type']}'. "
                        f"Supported: {', '.join(sorted(SUPPORTED_FIELD_TYPES))}"
                    )
                if field["type"] in ("radio", "checkbox") and not isinstance(field.get("options"), list):
                    raise ValueError(f"Field '{field['key']}' of type '{field['type']}' must have an 'options' list")

        return self


class FormTemplateResponse(BaseModel):
    id: int
    name: str
    version: int
    policy_provider_id: UUID
    schema_json: dict[str, Any]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

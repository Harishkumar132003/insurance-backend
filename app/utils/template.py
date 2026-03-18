import re
from typing import Any


def render_template(data: Any, context: dict) -> Any:
    """Recursively replace {{variable}} placeholders in data using context values."""
    if isinstance(data, str):
        def replacer(match):
            key = match.group(1).strip()
            value = context.get(key, match.group(0))
            # If the entire string is a single placeholder, return the raw value
            # (preserves types like int, dict, etc.)
            if match.group(0) == data:
                return value
            return str(value)

        # Check if entire string is a single placeholder
        single_match = re.fullmatch(r"\{\{(\s*\w+\s*)\}\}", data)
        if single_match:
            key = single_match.group(1).strip()
            return context.get(key, data)

        return re.sub(r"\{\{(\s*\w+\s*)\}\}", replacer, data)

    if isinstance(data, dict):
        return {k: render_template(v, context) for k, v in data.items()}

    if isinstance(data, list):
        return [render_template(item, context) for item in data]

    return data


def extract_value(data: Any, path: str) -> Any:
    """Extract a nested value using dot notation (e.g., 'data.token')."""
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            current = current[idx] if idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def extract_fields(response_data: Any, mapping: dict[str, str]) -> dict[str, Any]:
    """Extract multiple fields from response using a response_mapping dict."""
    result = {}
    for context_key, path in mapping.items():
        result[context_key] = extract_value(response_data, path)
    return result

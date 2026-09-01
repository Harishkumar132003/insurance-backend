"""Shared plumbing for the hybrid pipeline: request tracing, chat models, embeddings.

Its own ContextVar rather than importing nl_sql_service's, so the two pipelines'
traces never interleave and neither can break the other.
"""
import contextvars
import itertools
import logging

from app.core.config import settings

logger = logging.getLogger("app.hybrid")

_rid: contextvars.ContextVar[str] = contextvars.ContextVar("hybrid_rid", default="-")
_seq = itertools.count(1)


def new_rid() -> str:
    rid = format(next(_seq) % 10000, "04d")
    _rid.set(rid)
    return rid


def rid() -> str:
    return _rid.get()


def log(step: str, msg: str = "", *args) -> None:
    """One step line: [hybrid:0007] STEP | detail."""
    body = (msg % args) if args else msg
    logger.info("[hybrid:%s] %-10s%s", _rid.get(), step, (" | " + body) if body else "")


def short(text: str, n: int = 300) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n] + "…"


# Reasoning models reject a temperature argument.
_REASONING_HINTS = ("o1", "o3", "o4", "gpt-5")


def chat_model(structured=None, temperature: float = 0.0, sql: bool = False):
    """LangChain chat model, optionally bound to a structured-output schema."""
    from langchain.chat_models import init_chat_model

    name = settings.AI_SQL_MODEL if sql else settings.AI_QUERY_MODEL
    kwargs = {"api_key": settings.OPENAI_API_KEY}
    tail = name.split(":", 1)[-1].lower()
    if not any(tail.startswith(h) for h in _REASONING_HINTS):
        kwargs["temperature"] = temperature
    model = init_chat_model(name, **kwargs)
    return model.with_structured_output(structured) if structured is not None else model


def msg_text(resp) -> str:
    """Plain text out of a LangChain message, whose content may be a list of parts."""
    content = getattr(resp, "content", resp)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
        return "".join(parts).strip()
    return str(content or "").strip()


async def embed_many(texts: list[str]) -> list[list[float]]:
    """Embed several strings in ONE OpenAI call."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    resp = await client.embeddings.create(model=settings.EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]

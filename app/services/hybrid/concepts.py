"""Concept extraction — question -> canonical schema phrases.

The stage the rest of the pipeline hangs off. Everything downstream searches on what
this produces, so a miss here cannot be recovered later.

Deliberately different from the production pipeline's metrics/filters split, whose only
purpose was to decide which Qdrant `type` filter to apply. Here each phrase is a
complete, self-contained retrieval query written in the vocabulary of the semantic layer
("preauth approved amount"), and literal values are lifted OUT into `entities` so they
can be handed straight to SQL generation instead of being dropped.
"""
import re

from app.schemas.hybrid import Concepts, Entity, SearchPhrase
from app.services.hybrid.common import chat_model, log
from app.services.hybrid.prompts import CONCEPTS_PROMPT

# A phrase is supposed to name a CATEGORY, never a value. These catch the model
# occasionally leaking a literal through anyway.
_HAS_DIGITS = re.compile(r"\d")
_QUOTED = re.compile(r"['\"]")


def _leaks_literal(phrase: str, entities: list[Entity]) -> bool:
    low = phrase.lower()
    if _HAS_DIGITS.search(low) or _QUOTED.search(phrase):
        return True
    return any(e.value and e.value.lower() in low for e in entities)


def _clean(concepts: Concepts, question: str) -> Concepts:
    """Normalise, drop phrases that leaked a literal, and guarantee a usable result."""
    seen: set[str] = set()
    kept: list[SearchPhrase] = []
    dropped: list[str] = []

    for p in concepts.phrases:
        phrase = " ".join((p.phrase or "").split()).lower()
        if not phrase or phrase in seen:
            continue
        if _leaks_literal(phrase, concepts.entities):
            dropped.append(phrase)
            continue
        seen.add(phrase)
        kept.append(SearchPhrase(
            phrase=phrase,
            role=p.role,
            expansions=[e.strip().lower() for e in (p.expansions or []) if e and e.strip()],
        ))

    if dropped:
        log("concepts", "dropped %d phrase(s) containing a literal value: %s", len(dropped), dropped)

    # Never leave retrieval with nothing to search on — the production pipeline raises
    # here, which takes the whole request down.
    if not kept:
        fallback = " ".join((concepts.normalized_question or question).split()).lower()[:120]
        log("concepts", "no usable phrases — falling back to the whole question")
        kept = [SearchPhrase(phrase=fallback, role="metric", expansions=[])]

    concepts.phrases = kept
    concepts.normalized_question = " ".join(
        (concepts.normalized_question or question).split()
    )
    concepts.entities = [
        Entity(value=e.value.strip(), kind=e.kind)
        for e in concepts.entities if e.value and e.value.strip()
    ]
    return concepts


async def extract_concepts(question: str) -> Concepts:
    structured = chat_model(Concepts)
    out: Concepts = await structured.ainvoke([
        {"role": "system", "content": CONCEPTS_PROMPT},
        {"role": "user", "content": question},
    ])
    out = _clean(out, question)

    log("concepts", "%d phrase(s): %s", len(out.phrases),
        [(p.phrase, p.role) for p in out.phrases])
    if out.entities:
        log("concepts", "entities: %s", [(e.value, e.kind) for e in out.entities])
    if out.time_phrase:
        log("concepts", "time: %s", out.time_phrase)
    return out


def entity_hint(concepts: Concepts, resolutions: list | None = None) -> str:
    """The literal values, rendered for the SQL prompt. This is what the production
    pipeline throws away — and why it answers 'no records found' for real providers.

    `resolutions` are identifier probe results. They are appended last and labelled as
    verified, because a `kind` is a guess by the extractor while a resolution is a fact
    from the database — and when they disagree the database wins.
    """
    if not concepts.entities and not concepts.time_phrase and not resolutions:
        return ""
    lines = []
    if concepts.entities:
        lines.append("LITERAL VALUES from the question (filter on these):")
        for e in concepts.entities:
            lines.append(f"  {e.kind}: {e.value}")
    if concepts.time_phrase:
        lines.append(f"TIME PERIOD asked for: {concepts.time_phrase}")

    if resolutions:
        from app.services.hybrid.identifiers import resolution_hint

        hint = resolution_hint(resolutions)
        if hint:
            lines.append("")
            lines.append(hint)
    return "\n".join(lines)

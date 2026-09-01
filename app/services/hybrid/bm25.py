"""Hand-rolled BM25 over the Cube member catalog.

`rank_bm25` is not installed and pulling in a dependency for ~60 lines of arithmetic
isn't worth a Docker rebuild, so this is the textbook Okapi BM25 implemented directly.

This arm exists because dense embeddings are weak on exactly the vocabulary this domain
runs on: ADR, NMI, UTR, TAT, SLA, short-pay, shortfall, disallowance, UHID, TPA. Those
are rare tokens with high IDF — precisely where a lexical index beats a 1536-dim vector
trained mostly on general web text.

Two implementation notes that matter:

  * fields are weighted by REPEATING their tokens (name x3, title x2), which is the
    standard trick for field-weighted BM25 without maintaining per-field indexes;
  * the Qdrant `text` blob is deliberately NOT used as the document. Every document in
    the existing index starts with the literal labels "Domain View:", "Cube:", "Type:",
    "Name:", "Title:", "Description:" — six tokens with a document frequency of 100%,
    which contribute nothing and drag the length normaliser around.
"""
import math
import re
from collections import Counter

from app.services.hybrid.cube_meta import Member

K1 = 1.5
B = 0.75

# Repeat count per field when building a document.
FIELD_WEIGHTS = {"name": 3, "title": 2, "description": 1, "view": 1}

_STOP = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "by", "is", "are",
    "was", "were", "be", "been", "with", "this", "that", "these", "those", "it", "its",
    "as", "at", "from", "use", "used", "using", "only", "any", "all", "not", "no",
}

# Query-time only, so document IDF stays honest. Each key expands to extra query tokens.
_SYNONYMS: dict[str, list[str]] = {
    "adr": ["nmi", "query", "queries", "information", "additional"],
    "nmi": ["adr", "query", "queries", "information"],
    "query": ["adr", "nmi"],
    "queries": ["adr", "nmi"],
    "tat": ["turnaround", "turn", "around", "time", "transition"],
    "turnaround": ["tat", "transition", "time"],
    "sla": ["breach", "breached", "tat", "turnaround"],
    "utr": ["settlement", "number", "remittance", "bank", "batch"],
    "remittance": ["utr", "settlement", "batch"],
    "tpa": ["administrator", "provider", "insurer"],
    "preauth": ["pre", "auth", "authorization", "authorisation", "preauthorization"],
    "authorization": ["preauth", "auth"],
    "shortfall": ["disallowance", "deduction", "gap", "shortpay", "short"],
    "disallowance": ["shortfall", "deduction", "shortpay", "deducted", "lost"],
    "shortpay": ["disallowance", "shortfall", "deduction"],
    "denied": ["denial", "rejected", "reject", "rejection"],
    "denial": ["denied", "rejected"],
    "pending": ["awaiting", "waiting", "stuck", "sitting"],
    "insurer": ["provider", "payer", "insurance", "tpa"],
    "provider": ["insurer", "insurance", "payer", "tpa"],
    "enhancement": ["enhance", "topup", "top", "additional"],
    "uhid": ["patient", "identifier", "unique"],
    "settled": ["settlement", "paid", "payout", "disbursed"],
    "settlement": ["settled", "payout", "disbursed", "remittance"],
    "corporate": ["employer", "company"],
    "converted": ["conversion", "moved", "converted"],
    "raised": ["requested", "billed", "claimed", "submitted"],
    "approved": ["sanctioned", "approval"],
    "count": ["number", "total", "volume", "how", "many"],
    "amount": ["money", "monetary", "value", "sum", "total"],
    "average": ["avg", "mean"],
    "email": ["correspondence", "mail"],
}

_SPLIT = re.compile(r"[^a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, split on any non-alphanumeric (which handles snake_case and hyphens),
    drop stopwords and 1-char noise. Two-char tokens are KEPT so acronyms survive."""
    if not text:
        return []
    text = text.lower()
    # Normalise the many spellings of pre-auth to a single token before splitting.
    text = re.sub(r"\bpre[\s\-_]?auth(orization|orisation)?\b", "preauth", text)
    text = re.sub(r"\bshort[\s\-_]?pay\b", "shortpay", text)
    text = re.sub(r"\bturn[\s\-_]?around\b", "turnaround", text)
    toks = [t for t in _SPLIT.split(text) if t]
    return [t for t in toks if len(t) > 1 and t not in _STOP]


def expand_query(tokens: list[str]) -> list[str]:
    """Add domain synonyms. Deduped, so a long expansion list can't swamp the score."""
    out = list(tokens)
    for t in tokens:
        out.extend(_SYNONYMS.get(t, ()))
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _document(m: Member) -> list[str]:
    """Field-weighted bag of tokens for one member."""
    toks: list[str] = []
    toks += tokenize(m.name) * FIELD_WEIGHTS["name"]
    toks += tokenize(m.title) * FIELD_WEIGHTS["title"]
    toks += tokenize(m.description) * FIELD_WEIGHTS["description"]
    toks += tokenize(m.view) * FIELD_WEIGHTS["view"]
    # The kind is a real signal: "count"/"amount" questions want measures.
    toks += tokenize({"measure": "metric measure", "segment": "filter flag boolean",
                      "dimension": "attribute field"}[m.kind])
    return toks


class Bm25Index:
    def __init__(self, catalog: list[Member]):
        self.qnames: list[str] = []
        self.freqs: list[Counter] = []
        self.lengths: list[int] = []
        df: Counter = Counter()

        for m in catalog:
            toks = _document(m)
            tf = Counter(toks)
            self.qnames.append(m.qname)
            self.freqs.append(tf)
            self.lengths.append(len(toks))
            df.update(tf.keys())

        self.n = len(self.qnames)
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 0.0
        # Okapi IDF with the +1 smoothing that keeps common terms non-negative.
        self.idf = {
            t: math.log(1 + (self.n - d + 0.5) / (d + 0.5))
            for t, d in df.items()
        }

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        tokens = expand_query(tokenize(query))
        if not tokens or not self.n:
            return []

        scores = [0.0] * self.n
        for t in tokens:
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i in range(self.n):
                f = self.freqs[i].get(t)
                if not f:
                    continue
                denom = f + K1 * (1 - B + B * self.lengths[i] / self.avgdl)
                scores[i] += idf * (f * (K1 + 1)) / denom

        ranked = sorted(
            ((self.qnames[i], s) for i, s in enumerate(scores) if s > 0),
            key=lambda kv: -kv[1],
        )
        return ranked[:k]


_index: Bm25Index | None = None
_index_size = 0


def get_index(catalog: list[Member]) -> Bm25Index:
    """Cached index, rebuilt when the catalog changes size (i.e. after a /meta refresh)."""
    global _index, _index_size
    if _index is None or _index_size != len(catalog):
        _index = Bm25Index(catalog)
        _index_size = len(catalog)
    return _index

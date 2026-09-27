"""A local embedder so knowledge search works with no API key.

Both the ingest path (worker) and the query path (agent-runtime) import this,
because a vector index is only meaningful if everything in it was produced the
same way. Putting it in packages/db is what puts it on both their PYTHONPATHs.

## Why this exists

Embeddings were the one credential with no fallback. Without an OpenAI or
Azure OpenAI key, `seed_kb` produced empty collections, every ingest came back
DEGRADED, and any agent calling `knowledge_search` answered that it could not
look anything up. On a fresh clone — the case the README invites people into —
that is most of the interesting behaviour switched off. Anthropic has no
embeddings endpoint, so a Claude subscription cannot fill the gap either.

## What it actually is

The hashing trick: word and character n-grams hashed into a fixed number of
buckets, sub-linear term frequency, then L2 normalised. Cosine over these is
lexical retrieval, near enough to hashed TF-IDF. It is **not semantic** — it
will not connect "myocardial infarction" to "heart attack" the way a trained
model does. It will reliably find the chunk that contains the words you typed,
which is the difference between a knowledge base that answers and one that
does not.

## Why 1536 dimensions

The pgvector column is `vector(1536)`, chosen for text-embedding-3-small.
Matching it means no migration and no second column. Cosine similarity is
unaffected by the choice of bucket count beyond collision rate.

## The rule that matters

A collection must be queried with the embedder that ingested it. Vectors from
two different schemes share a space but nothing else, and mixing them returns
confident nonsense. `knowledge_bases.embedding_model` records which one was
used; `embedder_id()` is what goes in that column.
"""

from __future__ import annotations

import hashlib
import math
import os
import re

DIM = 1536
MODEL_ID = "local-hashing-v1"

_WORD = re.compile(r"[a-z0-9]+")
# Words that appear in most documents and so separate nothing.
_STOP = frozenset(
    """a an and are as at be been but by for from had has have he her his in is it
    its of on or that the their there these they this to was were will with would
    you your we our us i""".split()
)


def is_enabled() -> bool:
    """True when nothing better is configured, or when explicitly asked for.

    ABENIX_LOCAL_EMBEDDINGS=1 forces it even with a provider key present, which
    is how you get a deterministic, offline, zero-cost test run.
    """
    forced = os.environ.get("ABENIX_LOCAL_EMBEDDINGS", "").strip().lower()
    if forced in {"1", "true", "yes"}:
        return True
    if forced in {"0", "false", "no"}:
        return False
    azure = os.environ.get("AZURE_OPENAI_API_KEY", "") and (
        os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        or os.environ.get("AZURE_OPENAI_API_BASE", "")
    )
    return not (azure or os.environ.get("OPENAI_API_KEY", ""))


def embedder_id() -> str:
    return MODEL_ID


def _bucket(token: str) -> int:
    # blake2b keeps this stable across processes and Python versions, which
    # hash() does not — a PYTHONHASHSEED change would silently invalidate a
    # whole index.
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % DIM


def _tokens(text: str) -> list[str]:
    words = [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]
    grams: list[str] = list(words)
    # Word bigrams carry a little order, which pure bag-of-words loses.
    grams += [f"{a}_{b}" for a, b in zip(words, words[1:])]
    # Character 4-grams on longer words, so a typo or an inflection still
    # overlaps its root rather than missing entirely.
    for w in words:
        if len(w) >= 6:
            grams += [f"#{w[i:i + 4]}" for i in range(len(w) - 3)]
    return grams


def embed(text: str) -> list[float]:
    """One text to one L2-normalised vector of length DIM."""
    counts: dict[int, float] = {}
    for tok in _tokens(text):
        b = _bucket(tok)
        counts[b] = counts.get(b, 0.0) + 1.0
    if not counts:
        return [0.0] * DIM
    vec = [0.0] * DIM
    for b, tf in counts.items():
        # Sub-linear scaling: the twentieth occurrence of a word says much
        # less than the second.
        vec[b] = 1.0 + math.log(tf)
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def embed_many(texts: list[str]) -> list[list[float]]:
    return [embed(t) for t in texts]

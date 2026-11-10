"""A tiny local embedding: hashed bag of words and word pairs.

No model download, no API key, same text always gives the same vector.
Good enough to match an alert to the right runbook. Swap in a real
embedding model later by changing only this file (keep EMBEDDING_DIM in sync).
"""
import hashlib
import math
import re

DIM = 256


def embed(text: str) -> list[float]:
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    vec = [0.0] * DIM
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))

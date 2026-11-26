"""Local hybrid retrieval over original, source-linked CBC notes."""

from __future__ import annotations

import json
import re
import hashlib
import threading
import time
from pathlib import Path
import numpy as np
import config
from provider import embed, ProviderError

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent
DOCUMENTS = json.loads((ROOT / "knowledge_base.json").read_text(encoding="utf-8"))


def tokens(value: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+", value.lower())


SEARCH_TEXT = [f"{doc['title']} {doc['topic']} {doc['text']}" for doc in DOCUMENTS]
BM25 = BM25Okapi([tokens(text) for text in SEARCH_TEXT])
VECTORIZER = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
DOC_VECTORS = VECTORIZER.fit_transform(SEARCH_TEXT)

SYNONYMS = {
    "hb": "hemoglobin", "hgb": "hemoglobin", "haemoglobin": "hemoglobin",
    "wbc": "white blood cell count", "leukocytes": "white blood cell count",
    "rbc": "red blood cell count", "erythrocytes": "red blood cell count",
    "hct": "hematocrit", "pcv": "hematocrit", "plt": "platelets",
    "mcv": "mean corpuscular volume", "normal": "reference range",
}


def expand_query(query: str) -> str:
    words = tokens(query)
    expansions = [SYNONYMS[word] for word in words if word in SYNONYMS]
    return query + " " + " ".join(expansions)


def retrieve_notes(query: str, limit: int = 3) -> list[dict]:
    """Fuse BM25 and TF-IDF ranks; always return stable source IDs."""
    expanded = expand_query(query)
    bm25_scores = BM25.get_scores(tokens(expanded))
    tfidf_scores = cosine_similarity(VECTORIZER.transform([expanded]), DOC_VECTORS)[0]
    bm25_order = sorted(range(len(DOCUMENTS)), key=lambda i: bm25_scores[i], reverse=True)
    tfidf_order = sorted(range(len(DOCUMENTS)), key=lambda i: tfidf_scores[i], reverse=True)
    query_terms = set(tokens(expanded)) - {"what", "does", "mean", "my", "is", "the", "a", "and"}
    ranks = {i: 1 / (60 + bm25_order.index(i)) + 1 / (60 + tfidf_order.index(i)) +
             0.003 * len(query_terms.intersection(tokens(DOCUMENTS[i]["title"]))) for i in range(len(DOCUMENTS))}
    matches = sorted(ranks, key=ranks.get, reverse=True)
    # A query with no meaningful lexical match must not pull a random source into the answer.
    return [DOCUMENTS[i] for i in matches if bm25_scores[i] > 0 or tfidf_scores[i] > 0][:limit]


_index_lock = threading.Lock()
_dense = None
_retry_after = 0.0


def _dense_index():
    global _dense
    with _index_lock:
        if _dense is not None:
            return _dense
        fingerprint = hashlib.sha256((config.EMBEDDING_MODEL + json.dumps(SEARCH_TEXT)).encode()).hexdigest()[:16]
        cache = ROOT / '.cache' / f'knowledge-{fingerprint}.json'
        if cache.exists():
            vectors = json.loads(cache.read_text(encoding='utf-8'))
        else:
            vectors = embed(SEARCH_TEXT)
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps(vectors), encoding='utf-8')
        _dense = np.asarray(vectors)
        return _dense


def search_notes(query: str, limit: int = 4) -> tuple[list[dict], str]:
    """Fuse dense semantic retrieval with local lexical ranks; cache public KB only."""
    global _retry_after
    lexical = retrieve_notes(query, limit=len(DOCUMENTS))
    if not config.api_key() or not config.SEMANTIC or time.monotonic() < _retry_after:
        return lexical[:limit], 'BM25 + TF-IDF'
    try:
        dense = _dense_index()
        vector = np.asarray(embed([query])[0]).reshape(1, -1)
        similarities = cosine_similarity(vector, dense)[0]
        dense_order = np.argsort(-similarities).tolist()
        lexical_ids = [doc['id'] for doc in lexical]
        scored = []
        for index, doc in enumerate(DOCUMENTS):
            if similarities[index] < 0.22 and doc['id'] not in lexical_ids:
                continue
            lex_rank = lexical_ids.index(doc['id']) if doc['id'] in lexical_ids else len(DOCUMENTS) + 20
            score = 1 / (60 + dense_order.index(index)) + 1 / (60 + lex_rank)
            scored.append((score, doc))
        return [dict(doc, retrieval_score=round(score, 4)) for score, doc in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]], 'Semantic + BM25 + TF-IDF'
    except (ProviderError, ValueError, OSError, KeyError):
        _retry_after = time.monotonic() + 60
        return lexical[:limit], 'BM25 + TF-IDF (semantic unavailable)'

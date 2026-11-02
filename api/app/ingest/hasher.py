"""Fact hashes (through chain/merkle.py, the only Merkle implementation) and embeddings."""
import threading

import numpy as np

from app.chain import merkle

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

_model = None
_model_lock = threading.Lock()


def _get_model():
    # Imported here because torch would otherwise slow every API start and test run.
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
        return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Normalised vectors, so a dot product is the cosine."""
    return _get_model().encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)


def hash_fact(idx: int, text: str) -> tuple[str, str]:
    text_hash = merkle.text_hash(text)
    return text_hash, merkle.leaf(idx, text_hash)


def fact_root(leaves: list[str]) -> str:
    return merkle.build_tree(leaves)

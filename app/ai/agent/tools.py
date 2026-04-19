"""
tools.py — Drug lookup + PharmEasy search
Reads from local drug_db.json + FAISS index for drug info.
Uses pharmeasy_scraper.py for live medicine search.
"""

import json
import re
from pathlib import Path

from synonyms import normalize, parse_composition
import pharmeasy_scraper

# ── Load local DB ─────────────────────────────────────────────────────────────
_DB_PATH   = Path(__file__).parent / "drug_db.json"
_FAISS_DIR = Path(__file__).parent / "faiss_index"

try:
    with open(_DB_PATH) as f:
        DRUG_DB: dict = json.load(f)
    print(f"[tools] Loaded drug_db.json — {len(DRUG_DB):,} records")
except FileNotFoundError:
    DRUG_DB = {}
    print("[tools] WARNING: drug_db.json not found. Run build_db.py first.")

# Lazy-load FAISS
_faiss_index  = None
_faiss_chunks = None
_embedder     = None


def _load_faiss():
    global _faiss_index, _faiss_chunks, _embedder
    if _faiss_index is not None:
        return True
    try:
        import faiss
        from sentence_transformers import SentenceTransformer
        _faiss_index = faiss.read_index(str(_FAISS_DIR / "index.faiss"))
        with open(_FAISS_DIR / "chunks.json") as f:
            _faiss_chunks = json.load(f)
        _embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return True
    except Exception as e:
        print(f"[tools] FAISS not available: {e}")
        return False


# ── 1. Drug lookup ────────────────────────────────────────────────────────────

def lookup_drug(name: str) -> dict:
    key = normalize(name)

    if key in DRUG_DB:
        return {"found": True, **DRUG_DB[key]}

    for db_key, record in DRUG_DB.items():
        if db_key.startswith(key) or key.startswith(db_key):
            return {"found": True, **record}

    name_lower = name.lower()
    for db_key, record in DRUG_DB.items():
        brands_lower = [b.lower() for b in record.get("brands", [])]
        if any(name_lower in b or b in name_lower for b in brands_lower):
            return {"found": True, **record}

    return {
        "found": False, "salt": name, "brands": [],
        "uses": "", "warnings": "", "side_effects": "", "interactions": ""
    }


# ── 2. RAG query ──────────────────────────────────────────────────────────────

def rag_query(query: str, top_k: int = 3) -> list[dict]:
    if not _load_faiss():
        return []
    import numpy as np
    query_vec = _embedder.encode([query]).astype("float32")
    norm      = np.linalg.norm(query_vec, axis=1, keepdims=True)
    query_vec = query_vec / (norm + 1e-9)
    scores, indices = _faiss_index.search(query_vec, top_k)
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        chunk = _faiss_chunks[idx]
        results.append({
            "salt":   chunk["salt"],
            "brands": chunk["brands"],
            "text":   chunk["text"],
            "score":  float(score),
        })
    return results


# ── 3. Interaction check ──────────────────────────────────────────────────────

def check_interactions(medicine_names: list[str]) -> list[str]:
    warnings   = []
    normalized = [(n, normalize(n)) for n in medicine_names]

    for orig_name, norm_name in normalized:
        record           = lookup_drug(orig_name)
        interaction_text = record.get("interactions", "").lower()
        if not interaction_text:
            continue
        for other_orig, other_norm in normalized:
            if other_orig == orig_name:
                continue
            if other_norm in interaction_text or other_orig.lower() in interaction_text:
                warnings.append(
                    f"⚠  {orig_name.title()} + {other_orig.title()}: "
                    f"possible interaction — check with your doctor"
                )

    return list(dict.fromkeys(warnings))


# ── 4. PharmEasy search (replaces Netmeds) ───────────────────────────────────

def search_medicines_pharmeasy(medicines: list[dict], top_n: int = 3) -> list[dict]:
    """
    Search PharmEasy in parallel for all medicines.
    Returns list of results with top_n product links each.
    """
    return pharmeasy_scraper.search_all_parallel(medicines, top_n=top_n)


def format_pharmeasy_results(results: list[dict]) -> str:
    """Format PharmEasy results for CLI display."""
    return pharmeasy_scraper.format_results(results)


# ── 5. Drug summary for LLM context ──────────────────────────────────────────

def format_drug_summary(medicine: dict) -> str:
    name   = medicine["name"]
    dose   = medicine.get("dosage", "?")
    freq   = medicine.get("frequency", "?")
    record = lookup_drug(name)

    uses    = record.get("uses", "")
    warning = record.get("warnings", "")
    se      = record.get("side_effects", "")

    lines = [f"\n  [{name}]  {dose}  —  {freq}"]
    if uses:
        lines.append(f"  Use     : {uses[:200]}")
    if warning:
        lines.append(f"  Warning : {warning[:200]}")
    if se:
        lines.append(f"  Side FX : {se[:150]}")
    if not record["found"]:
        lines.append("  (Not in local DB — ask your doctor or pharmacist)")

    return "\n".join(lines)
"""
build_db.py — One-time script to build drug_db.json + FAISS index

What it does:
  1. Downloads Indian Medicine Dataset CSV (253k rows) from GitHub
  2. Parses salt → brand mappings
  3. For each unique salt, fetches drug info from openFDA (with synonym mapping)
  4. Builds drug_db.json (structured lookup)
  5. Builds FAISS index (semantic RAG)

Run once:
  pip install requests pandas faiss-cpu sentence-transformers tqdm
  python build_db.py

Output files (put these next to agent.py):
  drug_db.json          ← structured lookup DB
  faiss_index/          ← FAISS semantic index folder
    index.faiss
    chunks.json
"""

import json
import re
import time
import sys
from pathlib import Path
from collections import defaultdict

import requests
import pandas as pd
from tqdm import tqdm

# ── Paths ─────────────────────────────────────────────────────────────────────
OUT_DIR        = Path(".")
DB_PATH        = OUT_DIR / "drug_db.json"
FAISS_DIR      = OUT_DIR / "faiss_index"
CSV_CACHE      = OUT_DIR / "_medicine_data_cache.csv"

# ── Config ────────────────────────────────────────────────────────────────────
INDIAN_CSV_URL = (
    "https://raw.githubusercontent.com/junioralive/"
    "Indian-Medicine-Dataset/main/DATA/indian_medicine_data.csv"
)
OPENFDA_URL    = "https://api.fda.gov/drug/label.json"
MAX_BRANDS     = 5      # top N brands to store per salt
MIN_BRAND_FREQ = 2      # ignore brands seen less than N times in dataset
EMBED_MODEL    = "sentence-transformers/all-MiniLM-L6-v2"

# Import synonyms
sys.path.insert(0, str(OUT_DIR))
from synonyms import normalize, parse_composition, SYNONYM_MAP


# ── Step 1: Download & parse Indian CSV ───────────────────────────────────────

def download_csv() -> pd.DataFrame:
    if CSV_CACHE.exists():
        print(f"Using cached CSV: {CSV_CACHE}")
        return pd.read_csv(CSV_CACHE, low_memory=False)

    print("Downloading Indian Medicine Dataset (~30MB)...")
    resp = requests.get(INDIAN_CSV_URL, timeout=60)
    resp.raise_for_status()
    CSV_CACHE.write_bytes(resp.content)
    print(f"Saved to {CSV_CACHE}")
    return pd.read_csv(CSV_CACHE, low_memory=False)


def build_brand_map(df: pd.DataFrame) -> dict:
    """
    Returns: {normalized_salt: [brand1, brand2, ...]}
    Handles both single-salt and combination drugs.
    """
    salt_to_brands = defaultdict(list)

    for _, row in df.iterrows():
        brand = str(row.get("name", "")).strip()
        if not brand or brand == "nan":
            continue

        # Skip discontinued
        if str(row.get("Is_discontinued", "")).upper() == "TRUE":
            continue

        # Get compositions
        comp1 = str(row.get("short_composition1", "")).strip()
        comp2 = str(row.get("short_composition2", "")).strip()

        # Parse each composition field
        salts = []
        if comp1 and comp1 != "nan":
            salts.extend(parse_composition(comp1))
        if comp2 and comp2 != "nan":
            salts.extend(parse_composition(comp2))

        # Also add the raw normalized salt as key
        for salt in salts:
            if salt and len(salt) > 2:
                salt_to_brands[salt].append(brand)

    # Deduplicate + sort by frequency + trim
    result = {}
    for salt, brands in salt_to_brands.items():
        freq = defaultdict(int)
        for b in brands:
            freq[b] += 1
        top = sorted(
            [b for b, c in freq.items() if c >= MIN_BRAND_FREQ],
            key=lambda b: -freq[b],
        )[:MAX_BRANDS]
        if not top:
            top = list(dict.fromkeys(brands))[:MAX_BRANDS]
        result[salt] = top

    return result


# ── Step 2: Fetch drug info from openFDA ──────────────────────────────────────

def fetch_openfda(generic_name: str) -> dict:
    """
    Fetch uses, warnings, side effects, interactions from openFDA.
    Uses normalized (US INN) name for searching.
    Returns dict or empty dict if not found.
    """
    params = {
        "search": f'openfda.generic_name:"{generic_name}"',
        "limit":  1,
    }
    try:
        resp = requests.get(OPENFDA_URL, params=params, timeout=10)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return {}
        label = results[0]
        return {
            "uses":          _first(label, "indications_and_usage"),
            "warnings":      _first(label, "warnings") or _first(label, "warnings_and_cautions"),
            "side_effects":  _first(label, "adverse_reactions"),
            "interactions":  _first(label, "drug_interactions"),
            "dosage":        _first(label, "dosage_and_administration"),
            "contraindicated": _first(label, "contraindications"),
        }
    except Exception:
        return {}


def _first(label: dict, key: str) -> str:
    """Extract first item from a label array field, cleaned up."""
    val = label.get(key)
    if isinstance(val, list) and val:
        text = val[0]
        # Truncate very long strings
        text = re.sub(r"\s+", " ", text).strip()
        return text[:800] if len(text) > 800 else text
    return ""


# ── Step 3: Build drug_db.json ────────────────────────────────────────────────

def build_drug_db(brand_map: dict) -> dict:
    """
    For each unique salt:
      1. Normalize to US INN name
      2. Fetch openFDA info
      3. Merge everything into one record
    """
    db = {}
    unique_salts = list(brand_map.keys())
    print(f"\nFetching drug info for {len(unique_salts)} unique salts from openFDA...")
    print("(This will take ~15-20 minutes. Grab a chai ☕)\n")

    openfda_cache = {}  # avoid duplicate fetches for synonym-mapped names

    for salt in tqdm(unique_salts, desc="Building DB"):
        us_name = normalize(salt)  # e.g. paracetamol → acetaminophen

        # Check if we already fetched this (multiple Indian names → same US name)
        if us_name not in openfda_cache:
            info = fetch_openfda(us_name)
            # Fallback: try original name if normalized returns nothing
            if not info and us_name != salt:
                info = fetch_openfda(salt)
            openfda_cache[us_name] = info
            time.sleep(0.07)  # ~14 req/sec, well under 40/min free limit
        else:
            info = openfda_cache[us_name]

        db[salt] = {
            "salt":         salt,
            "us_name":      us_name,
            "brands":       brand_map.get(salt, []),
            "uses":         info.get("uses", ""),
            "warnings":     info.get("warnings", ""),
            "side_effects": info.get("side_effects", ""),
            "interactions": info.get("interactions", ""),
            "dosage_info":  info.get("dosage", ""),
            "contraindicated": info.get("contraindicated", ""),
        }

    return db


# ── Step 4: Build FAISS index ─────────────────────────────────────────────────

def build_faiss_index(db: dict):
    """
    Convert drug records → text chunks → embeddings → FAISS index.
    Saves:
      faiss_index/index.faiss
      faiss_index/chunks.json
    """
    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("\nSkipping FAISS build — install with:")
        print("  pip install faiss-cpu sentence-transformers")
        return

    FAISS_DIR.mkdir(exist_ok=True)

    print("\nBuilding FAISS index...")
    print(f"Loading embedding model: {EMBED_MODEL}")
    embedder = SentenceTransformer(EMBED_MODEL)

    chunks = []
    for salt, record in db.items():
        # Skip empty records
        if not any([record["uses"], record["warnings"], record["side_effects"]]):
            continue

        brands_str = ", ".join(record["brands"][:3]) if record["brands"] else "N/A"

        # Build one rich text chunk per drug
        parts = [f"{salt.title()} (also known as: {brands_str})"]

        if record["uses"]:
            parts.append(f"Uses: {record['uses'][:400]}")
        if record["warnings"]:
            parts.append(f"Warnings: {record['warnings'][:300]}")
        if record["side_effects"]:
            parts.append(f"Side effects: {record['side_effects'][:300]}")
        if record["interactions"]:
            parts.append(f"Drug interactions: {record['interactions'][:300]}")
        if record["dosage_info"]:
            parts.append(f"Dosage: {record['dosage_info'][:200]}")

        text = " | ".join(parts)

        chunks.append({
            "salt":   salt,
            "brands": record["brands"],
            "text":   text,
        })

    print(f"Embedding {len(chunks)} drug chunks...")
    texts     = [c["text"] for c in chunks]
    embeddings = embedder.encode(texts, show_progress_bar=True, batch_size=64)
    embeddings = embeddings.astype("float32")

    # Normalise for cosine similarity
    import numpy as np
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / (norms + 1e-9)

    dim   = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)  # Inner product = cosine on normalised vecs
    index.add(embeddings)

    faiss.write_index(index, str(FAISS_DIR / "index.faiss"))

    with open(FAISS_DIR / "chunks.json", "w") as f:
        json.dump(chunks, f, indent=2)

    print(f"FAISS index saved → {FAISS_DIR}/")
    print(f"  {len(chunks)} chunks indexed")
    print(f"  Embedding dim: {dim}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Drug DB Builder")
    print("=" * 60)

    # Step 1
    print("\n[1/4] Downloading Indian Medicine Dataset...")
    df = download_csv()
    print(f"  Loaded {len(df):,} rows")

    # Step 2
    print("\n[2/4] Building salt → brand map...")
    brand_map = build_brand_map(df)
    print(f"  Found {len(brand_map):,} unique salts/compositions")

    # Sample output
    sample_keys = ["acetaminophen", "metformin", "atorvastatin", "amoxicillin"]
    print("\n  Sample brand mappings:")
    for k in sample_keys:
        brands = brand_map.get(k, [])
        if brands:
            print(f"    {k:25s} → {brands[:3]}")

    # Step 3
    print("\n[3/4] Fetching drug info from openFDA...")
    db = build_drug_db(brand_map)

    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2)
    print(f"\n  drug_db.json saved → {DB_PATH}")
    print(f"  Total records: {len(db):,}")

    filled = sum(1 for r in db.values() if r["uses"])
    print(f"  Records with clinical info: {filled:,} ({100*filled//len(db)}%)")

    # Step 4
    print("\n[4/4] Building FAISS semantic index...")
    build_faiss_index(db)

    print("\n" + "=" * 60)
    print("  ✅ Build complete!")
    print("=" * 60)
    print(f"\n  Output files:")
    print(f"    {DB_PATH}")
    print(f"    {FAISS_DIR}/index.faiss")
    print(f"    {FAISS_DIR}/chunks.json")
    print(f"\n  Place these next to agent.py and you're ready.")


if __name__ == "__main__":
    main()

    
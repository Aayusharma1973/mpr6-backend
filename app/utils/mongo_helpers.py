"""
Utility helpers for MongoDB documents.
"""
from bson import ObjectId


def doc_to_dict(doc: dict) -> dict:
    """Convert a MongoDB document to a plain dict, turning _id → id."""
    if doc is None:
        return {}
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d


def str_to_oid(id_str: str) -> ObjectId:
    """Convert a string to a BSON ObjectId, raising ValueError if invalid."""
    try:
        return ObjectId(id_str)
    except Exception:
        raise ValueError(f"Invalid ObjectId: {id_str}")

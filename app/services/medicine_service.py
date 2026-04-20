"""
app/services/medicine_service.py
──────────────────────────────────
Business logic for Medicine CRUD + image-based creation.

Changes from original:
  - create_medicine_from_image now uses Qwen OCR (via app/utils/ocr.py)
    and creates ALL detected medicine documents per prescription.
  - scan_only_from_image: parse a prescription image without any DB write.
"""

from datetime import datetime, timezone
from fastapi import HTTPException, status, UploadFile
from bson import ObjectId
from app.database.mongo import medicines_col
from app.schemas.medicine_schemas import (
    MedicineCreate,
    MedicineUpdate,
    MedicineOut,
    ScanResult,
    ScannedMedicine,
)
from app.utils.mongo_helpers import doc_to_dict, str_to_oid
from app.utils.ocr import extract_from_image
from loguru import logger


def _medicine_out(doc: dict) -> MedicineOut:
    d = doc_to_dict(doc)
    return MedicineOut(**d)


async def create_medicine(user_id: str, data: MedicineCreate) -> MedicineOut:
    col = medicines_col()
    doc = {
        "user_id": user_id,
        **data.model_dump(),
        "created_at": datetime.now(timezone.utc),
    }
    result = await col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _medicine_out(doc)


async def create_medicine_from_image(user_id: str, file: UploadFile) -> list[MedicineOut]:
    """
    Upload a prescription image → Qwen OCR → store ALL detected medicines.
    """
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image files are accepted.",
        )

    image_bytes = await file.read()
    logger.info(f"Running Qwen OCR on image ({len(image_bytes)} bytes) for user {user_id}")
    parsed = await extract_from_image(image_bytes, content_type)

    if not parsed.get("medicines"):
        # If no medicines detected, we still return an empty list or could raise error.
        # Based on scan_only_from_image logic, if ocr_simulated or no medicines, it might be a failure.
        # But here we'll just return what was found.
        return []

    col = medicines_col()
    created_medicines = []
    
    for m in parsed["medicines"]:
        doc = {
            "user_id":       user_id,
            "name":          m.get("name", "Unknown"),
            "dosage":        m.get("dosage", "Unknown"),
            "frequency":     m.get("frequency", "Unknown"),
            "time_slots":    [],
            "instructions":  "",
            "duration_days": None,
            "ocr_raw":       parsed.get("ocr_raw", ""),
            "ocr_simulated": parsed.get("ocr_simulated", False),
            "created_at":    datetime.now(timezone.utc),
        }
        result = await col.insert_one(doc)
        doc["_id"] = result.inserted_id
        created_medicines.append(_medicine_out(doc))
        
    return created_medicines


async def scan_only_from_image(file: UploadFile) -> ScanResult:
    """
    Parse a prescription image with Qwen OCR and return all detected medicines.
    Nothing is written to the database.
    The frontend can review the results and then call POST /medicines/manual
    for each medicine the user confirms.
    """
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image files are accepted.",
        )

    image_bytes = await file.read()
    logger.info(f"Scan-only OCR on image ({len(image_bytes)} bytes)")
    parsed = await extract_from_image(image_bytes, content_type)

    if parsed.get("ocr_simulated") or not parsed.get("medicines"):
        return ScanResult(
            ok=False,
            medicines=[],
            raw_text=parsed.get("ocr_raw", ""),
            error=parsed.get("instructions", "OCR failed"),
        )

    medicines = [
        ScannedMedicine(
            name=m.get("name", "Unknown"),
            dosage=m.get("dosage", "Unknown"),
            frequency=m.get("frequency", "Unknown"),
        )
        for m in parsed["medicines"]
    ]

    return ScanResult(
        ok=True,
        medicines=medicines,
        raw_text=parsed.get("ocr_raw", ""),
        error=None,
    )


async def list_medicines(user_id: str) -> list[MedicineOut]:
    col = medicines_col()
    cursor = col.find({"user_id": user_id}).sort("created_at", -1)
    docs = await cursor.to_list(length=200)
    return [_medicine_out(d) for d in docs]


async def get_medicine(user_id: str, medicine_id: str) -> MedicineOut:
    col = medicines_col()
    doc = await col.find_one({"_id": str_to_oid(medicine_id), "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Medicine not found.")
    return _medicine_out(doc)


async def update_medicine(
    user_id: str, medicine_id: str, data: MedicineUpdate
) -> MedicineOut:
    col = medicines_col()
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update.")

    result = await col.find_one_and_update(
        {"_id": str_to_oid(medicine_id), "user_id": user_id},
        {"$set": update_data},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Medicine not found.")
    return _medicine_out(result)


async def delete_medicine(user_id: str, medicine_id: str) -> dict:
    col = medicines_col()
    result = await col.delete_one({"_id": str_to_oid(medicine_id), "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Medicine not found.")
    return {"detail": "Medicine deleted successfully."}
"""
app/utils/ocr.py
─────────────────
OCR utility — replaced pytesseract with the fine-tuned Qwen2-VL model.
Keeps the same public interface so medicine_service.py needs no changes.
"""
from loguru import logger
from app.ai import qwen_ocr


async def extract_from_image(image_bytes: bytes, content_type: str) -> dict:
    """
    Run Qwen OCR on the provided image bytes.
    Returns a dict compatible with what medicine_service.py expects:
      {
        "name":         str,
        "dosage":       str,
        "frequency":    str,
        "instructions": str,
        "ocr_raw":      str,
        "ocr_simulated": bool,
        "medicines":    list[dict]   ← full parsed list (new field)
      }
    """
    if not qwen_ocr.is_loaded():
        logger.warning("Qwen model not loaded — returning fallback.")
        return {
            "name":          "Medicine Name (model not loaded)",
            "dosage":        "Unknown",
            "frequency":     "Unknown",
            "instructions":  "Please verify with your pharmacist.",
            "ocr_raw":       "",
            "ocr_simulated": True,
            "medicines":     [],
        }

    result = await qwen_ocr.extract_medicines(image_bytes)

    if not result["ok"] or not result["medicines"]:
        logger.warning(f"Qwen OCR failed or returned empty: {result.get('error')}")
        return {
            "name":          "Unknown",
            "dosage":        "Unknown",
            "frequency":     "Unknown",
            "instructions":  "OCR processing failed. Please add manually.",
            "ocr_raw":       result.get("raw", ""),
            "ocr_simulated": True,
            "medicines":     [],
        }

    # For backward compat with medicine_service.py (which expects single fields),
    # use the FIRST medicine as the primary fields.
    # The full list is available in "medicines" for the scan-only endpoint.
    first = result["medicines"][0]
    return {
        "name":          first.get("name", "Unknown"),
        "dosage":        first.get("dosage", "Unknown"),
        "frequency":     first.get("frequency", "Unknown"),
        "instructions":  "",
        "ocr_raw":       result.get("raw", ""),
        "ocr_simulated": False,
        "medicines":     result["medicines"],   # full list
    }
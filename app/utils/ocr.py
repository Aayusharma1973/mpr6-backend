"""
OCR utility for prescription image parsing.
Uses pytesseract when available; falls back to a simulated result.
"""
import re
import io
from loguru import logger

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


def _parse_text(raw: str) -> dict:
    """
    Heuristically extract medicine fields from raw OCR text.
    Returns a dict with best-effort values.
    """
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    result: dict = {
        "name": "",
        "dosage": "",
        "frequency": "",
        "instructions": raw[:500],  # raw text stored for reference
    }

    dosage_pattern = re.compile(r"\b(\d+\.?\d*\s*(?:mg|mcg|ml|IU|g|units?))\b", re.I)
    freq_pattern = re.compile(
        r"\b(\d+\s*(?:x|times?)\s*(?:daily|a day)|once daily|twice daily|"
        r"thrice daily|every\s+\d+\s*hours?|OD|BD|TDS|QID)\b",
        re.I,
    )

    for line in lines:
        if not result["name"] and len(line) > 2:
            result["name"] = line  # first non-empty line → likely drug name
        dosage_match = dosage_pattern.search(line)
        if dosage_match and not result["dosage"]:
            result["dosage"] = dosage_match.group(0)
        freq_match = freq_pattern.search(line)
        if freq_match and not result["frequency"]:
            result["frequency"] = freq_match.group(0)

    return result


async def extract_from_image(image_bytes: bytes, content_type: str) -> dict:
    """
    Run OCR on the provided image bytes and return a parsed medicine dict.
    """
    if not OCR_AVAILABLE:
        logger.warning("pytesseract not available — returning simulated OCR result.")
        return {
            "name": "Medicine Name (OCR unavailable)",
            "dosage": "Dosage not extracted",
            "frequency": "1x Daily",
            "instructions": "Please verify with your pharmacist.",
            "ocr_raw": "",
            "ocr_simulated": True,
        }

    try:
        image = Image.open(io.BytesIO(image_bytes))
        raw_text = pytesseract.image_to_string(image)
        logger.debug(f"OCR raw output: {raw_text[:300]}")
        parsed = _parse_text(raw_text)
        parsed["ocr_raw"] = raw_text
        parsed["ocr_simulated"] = False
        return parsed
    except Exception as exc:
        logger.error(f"OCR failed: {exc}")
        return {
            "name": "Unknown",
            "dosage": "Unknown",
            "frequency": "Unknown",
            "instructions": "OCR processing failed. Please add manually.",
            "ocr_raw": "",
            "ocr_simulated": True,
        }

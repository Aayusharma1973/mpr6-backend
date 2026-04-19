"""
app/ai/qwen_ocr.py
──────────────────
Qwen2-VL OCR wrapper.

- Model is loaded ONCE at startup via `load_qwen_model()` called from main.py lifespan.
- `extract_medicines(image_bytes)` is the only public function the rest of the
  backend needs.  It runs inference in a thread-pool so it doesn't block the
  async event loop.
- Also exposes `answer_with_image(image_bytes, question, history)` for the
  image-chat endpoint — it reuses the same loaded model.
"""

import asyncio
import io
import json
import logging
import os
import re
import warnings
from pathlib import Path
from typing import Optional

import torch  # top-level import — surfaces CUDA/install errors immediately
from loguru import logger

# ── silence model-loading noise ───────────────────────────────────────────────
# NOTE: only suppress HF/transformers noise via env vars.
# DO NOT call logging.disable() at module level — it kills Python import
# error reporting and makes NameErrors impossible to diagnose.
# warnings.filterwarnings("ignore")
# os.environ["TRANSFORMERS_VERBOSITY"]        = "error"
# os.environ["TOKENIZERS_PARALLELISM"]        = "false"
# os.environ["BITSANDBYTES_NOWELCOME"]        = "1"
# os.environ["HF_HUB_DISABLE_PROGRESS_BARS"]  = "0"

# ── Config ────────────────────────────────────────────────────────────────────
BASE_MODEL      = "Qwen/Qwen2-VL-2B-Instruct"
# Path relative to where uvicorn is launched (backend root)
ADAPTER_PATH    = Path("app/ai/best_adapter")

OCR_PROMPT = (
    "You are a clinical pharmacist AI. "
    "Analyze this handwritten prescription image and extract all medicines.\n\n"
    "Return ONLY valid JSON — no markdown, no extra text:\n"
    '{"medicines": [{"name": "...", "dosage": "...", "frequency": "M-A-N"}]}\n\n'
    "Rules:\n"
    "- frequency format: morning-afternoon-night using 0/1 (e.g. \"1-0-1\")\n"
    "- dosage must include unit (mg, ml, g)\n"
    "- do not include text outside the JSON"
)

CHAT_WITH_IMAGE_SYSTEM = (
    "You are a friendly medical assistant. "
    "The user has shared a prescription image along with a question. "
    "Look at the image carefully and answer the question in simple, clear language. "
    "Do not scare the user. Keep answers brief and friendly."
)

# ── Module-level state (populated at startup) ─────────────────────────────────
_model     = None
_processor = None
_loaded    = False


def is_loaded() -> bool:
    return _loaded


def load_qwen_model() -> None:
    """
    Load base model + LoRA adapter into GPU memory.
    Called once from main.py lifespan — BLOCKS until done (~15-30s).
    """
    global _model, _processor, _loaded

    if _loaded:
        logger.info("Qwen model already loaded, skipping.")
        return

    from transformers import (
        Qwen2VLForConditionalGeneration,
        AutoProcessor,
        BitsAndBytesConfig,
    )
    from peft import PeftModel

    adapter_str = str(ADAPTER_PATH)
    logger.info(f"Loading Qwen2-VL base model: {BASE_MODEL}")
    logger.info(f"Loading LoRA adapter from:   {adapter_str}")

    cuda_available = torch.cuda.is_available()
    load_kwargs = {
        "device_map": "auto",
        "torch_dtype": torch.float16 if cuda_available else torch.float32,
    }

    if cuda_available:
        logger.info("CUDA detected, using 4-bit quantization.")
        load_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
    else:
        logger.warning("CUDA not detected! Falling back to CPU loading. This will be slow and memory-intensive.")
        # On CPU, bitsandbytes quantization is not supported
        load_kwargs["device_map"] = "cpu"

    try:
        base = Qwen2VLForConditionalGeneration.from_pretrained(
            BASE_MODEL,
            **load_kwargs
        )
    except Exception as e:
        logger.error(f"Failed to load base model: {e}")
        return

    _model = PeftModel.from_pretrained(base, adapter_str)
    _model.eval()

    _processor = AutoProcessor.from_pretrained(adapter_str)
    _loaded = True

    try:
        if cuda_available:
            used = torch.cuda.memory_allocated(0) / 1e9
            cap  = torch.cuda.get_device_properties(0).total_memory / 1e9
            logger.success(f"Qwen model loaded ✓  VRAM: {used:.1f}/{cap:.1f} GB")
        else:
            logger.success("Qwen model loaded on CPU ✓")
    except Exception:
        logger.success("Qwen model loaded ✓")


# ── Internal inference ────────────────────────────────────────────────────────

def _run_inference(image_bytes: bytes, prompt: str) -> str:
    """
    Blocking inference — runs in a thread pool.
    Takes raw image bytes and a text prompt, returns raw model output string.
    """
    from qwen_vl_utils import process_vision_info
    from PIL import Image

    if not _loaded:
        raise RuntimeError("Qwen model not loaded. Call load_qwen_model() first.")

    # Save bytes to a temp PIL image that qwen_vl_utils can consume
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": pil_img, "max_pixels": 1003520},
                {"type": "text",  "text": prompt},
            ],
        }
    ]

    text = _processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, _ = process_vision_info(messages)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = _processor(
        text=[text],
        images=image_inputs,
        padding=True,
        truncation=False,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        out = _model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
            repetition_penalty=1.1,
            temperature=1.0,
        )

    raw = _processor.decode(
        out[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    ).strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1][4:] if parts[1].startswith("json") else parts[1]

    return raw


def _run_chat_inference(image_bytes: bytes, question: str, history: list[dict]) -> str:
    """
    Blocking inference for image+text chat.
    history: list of {"role": "user"|"assistant", "content": str}
    """
    from qwen_vl_utils import process_vision_info
    from PIL import Image

    if not _loaded:
        raise RuntimeError("Qwen model not loaded.")

    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Build message list: system + history (text only) + new user message with image
    messages = [{"role": "system", "content": CHAT_WITH_IMAGE_SYSTEM}]

    # Inject previous text history (no images in history — just text)
    for turn in history:
        messages.append({
            "role": turn["role"],
            "content": [{"type": "text", "text": turn["content"]}],
        })

    # Final user message includes the image
    messages.append({
        "role": "user",
        "content": [
            {"type": "image", "image": pil_img, "max_pixels": 1003520},
            {"type": "text",  "text": question},
        ],
    })

    text = _processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, _ = process_vision_info(messages)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = _processor(
        text=[text],
        images=image_inputs,
        padding=True,
        truncation=False,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        out = _model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
            repetition_penalty=1.1,
            temperature=1.0,
        )

    return _processor.decode(
        out[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    ).strip()


# ── Public async API ──────────────────────────────────────────────────────────

async def extract_medicines(image_bytes: bytes) -> dict:
    """
    Run OCR on a prescription image.
    Returns:
      {"ok": True,  "medicines": [...]}   on success
      {"ok": False, "raw": "...", "error": "..."}  on parse failure
    """
    loop = asyncio.get_event_loop()
    try:
        raw = await loop.run_in_executor(None, _run_inference, image_bytes, OCR_PROMPT)
    except Exception as exc:
        logger.error(f"Qwen OCR inference failed: {exc}")
        return {"ok": False, "medicines": [], "raw": "", "error": str(exc)}

    try:
        parsed = json.loads(raw)
        medicines = parsed.get("medicines", [])
        return {"ok": True, "medicines": medicines, "raw": raw, "error": None}
    except json.JSONDecodeError:
        logger.warning(f"Qwen OCR returned non-JSON: {raw[:200]}")
        return {
            "ok": False,
            "medicines": [],
            "raw": raw,
            "error": "Model output was not valid JSON",
        }


async def answer_with_image(
    image_bytes: bytes,
    question: str,
    history: list[dict],
) -> str:
    """
    Answer a user question about a prescription image, with full chat history context.
    history: [{"role": "user"|"assistant", "content": str}, ...]
    Returns the assistant reply string.
    """
    loop = asyncio.get_event_loop()
    try:
        reply = await loop.run_in_executor(
            None, _run_chat_inference, image_bytes, question, history
        )
        return reply
    except Exception as exc:
        logger.error(f"Qwen image-chat inference failed: {exc}")
        return "Sorry, I couldn't process the image right now. Please try again."
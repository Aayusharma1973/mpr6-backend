"""
RxGuardian FastAPI Backend
==========================
Entry point — wires together all routers, middleware, lifespan events,
Swagger customisation, CORS, rate-limiting, and logging.
"""
import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.database.mongo import connect_mongo, close_mongo
from app.database.sqlite import init_sqlite
from app.routes import auth_routes, medicine_routes, chat_routes, tracking_routes

import torch

# ── Logging setup ─────────────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>",
    level="DEBUG",
)
logger.add("logs/rxguardian.log", rotation="10 MB", retention="7 days", level="INFO")

settings = get_settings()

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup → connect DBs + load AI models.  Shutdown → close connections."""
    logger.info("🚀 RxGuardian starting up …")

    # Databases
    await connect_mongo()
    await init_sqlite()

    # ── Load Qwen VLM into GPU memory ─────────────────────────────────────────
    # Non-blocking: server starts instantly, model loads in the background.
    # All OCR/image-chat endpoints return a friendly "still loading" message
    # until qwen_ocr.is_loaded() becomes True (~30-60s on GPU).
    async def _load_qwen_bg():
        try:
            from app.ai import qwen_ocr
            logger.info("Starting Qwen2-VL model loading in background …")
            await asyncio.to_thread(qwen_ocr.load_qwen_model)
            logger.success("✅ Qwen2-VL model ready — image endpoints now active.")
        except Exception as exc:
            import traceback
            logger.error(f"Qwen model background load failed: {exc}\n{traceback.format_exc()}")

    asyncio.create_task(_load_qwen_bg())

    yield

    logger.info("🛑 RxGuardian shutting down …")
    await close_mongo()


# ── App factory ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="RxGuardian API",
    description=(
        "## RxGuardian — Medicine Tracking Backend\n\n"
        "### Features\n"
        "- 🔐 **JWT Authentication** (register / login)\n"
        "- 💊 **Medicine CRUD** — manual entry or prescription image scan\n"
        "- 🤖 **RxGuardian AI Chat** — drug Q&A powered by Ollama (text) + Qwen VLM (image)\n"
        "- 📅 **Daily Tracking** — mark doses taken, auto-sync to MongoDB\n\n"
        "### Auth\n"
        "Use the **Authorize** button (🔒) and enter `Bearer <your_token>` after logging in.\n\n"
        "### New endpoints\n"
        "- `POST /api/v1/medicines/scan-only` — parse a prescription image, no DB write\n"
        "- `POST /api/v1/chat/with-image` — chat with a prescription image (multipart form)\n"
    ),
    version="1.1.0",
    contact={"name": "RxGuardian Team", "email": "dev@rxguardian.app"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ── Middleware ─────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Request logging middleware ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.debug(f"→ {request.method} {request.url.path}")
    response = await call_next(request)
    logger.debug(f"← {response.status_code} {request.url.path}")
    return response


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred."},
    )


# ── Routers ───────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth_routes.router,      prefix=API_PREFIX)
app.include_router(medicine_routes.router,  prefix=API_PREFIX)
app.include_router(chat_routes.router,      prefix=API_PREFIX)
app.include_router(tracking_routes.router,  prefix=API_PREFIX)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"], summary="Health check")
async def health():
    from app.ai import qwen_ocr
    return {
        "status":       "ok",
        "version":      "1.1.0",
        "app":          "RxGuardian",
        "qwen_loaded":  qwen_ocr.is_loaded(),
    }


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Welcome to RxGuardian API. Visit /docs for Swagger UI."}
"""
RxGuardian FastAPI Backend
==========================
Entry point — wires together all routers, middleware, lifespan events,
Swagger customisation, CORS, rate-limiting, and logging.
"""
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
    """Startup → connect DBs.  Shutdown → close connections."""
    logger.info("🚀 RxGuardian starting up …")
    await connect_mongo()
    await init_sqlite()
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
        "- 🤖 **RxGuardian AI Chat** — drug interaction & dosage Q&A\n"
        "- 📅 **Daily Tracking** — mark doses taken, auto-sync to MongoDB\n\n"
        "### Auth\n"
        "Use the **Authorize** button (🔒) and enter `Bearer <your_token>` after logging in."
    ),
    version="1.0.0",
    contact={"name": "RxGuardian Team", "email": "dev@rxguardian.app"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ── Middleware ─────────────────────────────────────────────────────────────────

# CORS — allow React Native / Expo dev clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
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

app.include_router(auth_routes.router, prefix=API_PREFIX)
app.include_router(medicine_routes.router, prefix=API_PREFIX)
app.include_router(chat_routes.router, prefix=API_PREFIX)
app.include_router(tracking_routes.router, prefix=API_PREFIX)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"], summary="Health check")
async def health():
    return {"status": "ok", "version": "1.0.0", "app": "RxGuardian"}


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Welcome to RxGuardian API. Visit /docs for Swagger UI."}

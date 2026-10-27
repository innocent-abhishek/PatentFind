import logging
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.api import api_router
from app.core.config import settings
from app.db.mongodb import check_mongodb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("patentfind")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="PatentFind - Keyword-based patent search engine with persistent inverted index",
    version="0.2.0"
)

# Configure CORS for local development with frontend (Vite)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes under /api
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", summary="Root endpoint")
def root():
    return {
        "app": settings.PROJECT_NAME,
        "version": "0.2.0",
        "description": "Keyword search engine for patents (2016-2023)",
        "docs_url": "/docs",
        "health_check": "/api/health"
    }


@app.get("/api/health", summary="Health check endpoint")
@app.get("/health", summary="Health check endpoint alias")
def health():
    try:
        is_mongo_ok = check_mongodb()
        if not is_mongo_ok:
            raise Exception("MongoDB ping failed")
        return {
            "status": "healthy",
            "database": "connected",
            "mongodb_url": settings.MONGODB_URL.split("@")[-1]  # Mask credentials if any
        }
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection error: {str(exc)}"
        )

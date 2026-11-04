import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.database.connection import get_connection_pool, get_db_connection
from app.api.v1.router import api_router

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
)
logger = logging.getLogger("smart_campus")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB pool
    logger.info("Initializing Smart Campus backend...")
    try:
        pool = get_connection_pool()
        logger.info(f"Database connection pool ready: {pool.pool_name}")
    except Exception as e:
        logger.error(f"Failed to connect to MySQL during startup: {e}")
    yield
    # Shutdown
    logger.info("Shutting down Smart Campus backend...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for Smart Campus Space & Resource Booking System with conflict-free scheduling and role-based access control.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# CORS Middleware
origins = settings.CORS_ORIGINS
if isinstance(origins, str):
    origins = [o.strip() for o in origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_origin_regex=r"https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please try again later."}
    )


@app.get("/health", tags=["Health"], summary="Health check endpoint")
def health_check():
    """Health check endpoint to verify backend status and database connectivity."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "healthy",
                "database": "connected",
                "service": settings.PROJECT_NAME,
            },
        )
    except Exception as exc:
        logger.warning(f"Health check DB warning: {exc}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "degraded",
                "database": "disconnected",
                "service": settings.PROJECT_NAME,
            },
        )


# Include API v1 Router
app.include_router(api_router, prefix=settings.API_V1_STR)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    reload_enabled = settings.ENVIRONMENT == "development" and os.getenv("UVICORN_RELOAD", "1") == "1"
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload_enabled)

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.s3 import ensure_bucket_exists

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("brain-api starting", environment=settings.environment)
    await ensure_bucket_exists()
    log.info("S3 bucket ready", bucket=settings.s3_bucket_name)
    yield
    log.info("brain-api shutting down")


app = FastAPI(
    title="Bedrock Brain API",
    version="0.1.0",
    description="RBAC-enforced shared second brain — notes stored in Nutanix Objects, metadata in Postgres.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


@app.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok", "environment": settings.environment}

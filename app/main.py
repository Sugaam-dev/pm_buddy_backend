from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
import structlog

from app.api.v1.actions import router as actions_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.auth import router as auth_router
from app.api.v1.calendar import router as calendar_router
from app.api.v1.chat import router as chat_router
from app.api.v1.dependencies import router as dependencies_router
from app.api.v1.intelligence import router as intelligence_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.projects import router as projects_router
from app.api.v1.realtime import router as realtime_router
from app.api.v1.risks import router as risks_router
from app.api.v1.search import router as search_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.tickets import router as tickets_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup_begins", app_name=settings.APP_NAME, env=settings.ENVIRONMENT)
    yield
    logger.info("shutdown_begins")
    await engine.dispose()


app = FastAPI(
    title="PM Buddy — AI Operations & Governance API",
    description="Backend API for enterprise AI operational intelligence, deterministic SLA governance, and HITL workflow execution.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
raw_origins = [
    origin.strip()
    for origin in settings.FRONTEND_URL.split(",")
    if origin.strip()
]
origins = list(set(raw_origins + [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health & Readiness
@app.get("/health", tags=["Observability"])
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENVIRONMENT}


@app.get("/ready", tags=["Observability"])
async def readiness():
    db_status = "down"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_status = "up"
    except Exception as e:
        logger.warning("database_readiness_check_failed", error=str(e))

    return {
        "status": "ready" if db_status == "up" else "degraded",
        "database": db_status,
        "environment": settings.ENVIRONMENT,
    }


# Include V1 API Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(tickets_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(risks_router, prefix="/api/v1")
app.include_router(calendar_router, prefix="/api/v1")
app.include_router(actions_router, prefix="/api/v1")
app.include_router(realtime_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(dependencies_router, prefix="/api/v1")
app.include_router(intelligence_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")

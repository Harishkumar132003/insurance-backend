import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401 — ensure all models are registered
from app.services.email_scheduler import start_email_scheduler, stop_email_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from app.routes.auth_routes import router as auth_router
from app.routes.user_routes import router as user_router
from app.routes.hospital_routes import router as hospital_router
from app.routes.hospital_config_routes import router as hospital_config_router
from app.routes.workflow_routes import router as workflow_router
from app.routes.hospital_prompt_routes import router as hospital_prompt_router
from app.routes.policy_provider_routes import router as policy_provider_router
from app.routes.form_template_routes import router as form_template_router
from app.routes.form_data_routes import router as form_data_router
from app.routes.email_routes import router as email_router
from app.routes.email_template_routes import router as email_template_router
from app.routes.claim_case_routes import router as claim_case_router
from app.routes.mock_routes import router as mock_router
from app.routes.cc_email_routes import router as cc_email_router

def _run_migrations():
    """Add missing columns to existing tables."""
    from sqlalchemy import text
    alter_statements = [
        "ALTER TABLE policy_provider_configs ADD COLUMN IF NOT EXISTS email VARCHAR",
        "ALTER TABLE claim_case_emails ADD COLUMN IF NOT EXISTS email_type VARCHAR",
        "ALTER TABLE claim_cases ADD COLUMN IF NOT EXISTS approved_amount NUMERIC(12,2)",
    ]
    with engine.connect() as conn:
        for stmt in alter_statements:
            conn.execute(text(stmt))
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    start_email_scheduler()
    yield
    stop_email_scheduler()


app = FastAPI(title="OASYS Backend", version="0.1.0", redirect_slashes=False, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(user_router, prefix="/api/v1")
app.include_router(hospital_router, prefix="/api/v1")
app.include_router(hospital_config_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(hospital_prompt_router, prefix="/api/v1")
app.include_router(policy_provider_router, prefix="/api/v1")
app.include_router(form_template_router, prefix="/api/v1")
app.include_router(form_data_router, prefix="/api/v1")
app.include_router(email_router, prefix="/api/v1")
app.include_router(email_template_router, prefix="/api/v1")
app.include_router(claim_case_router, prefix="/api/v1")
app.include_router(mock_router, prefix="/api/v1")
app.include_router(cc_email_router, prefix="/api/v1")


@app.get("/health")
def health_check():
    return {"status": "ok"}

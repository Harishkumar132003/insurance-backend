from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.auth_routes import router as auth_router
from app.routes.user_routes import router as user_router
from app.routes.hospital_routes import router as hospital_router
from app.routes.hospital_config_routes import router as hospital_config_router
from app.routes.workflow_routes import router as workflow_router
from app.routes.hospital_prompt_routes import router as hospital_prompt_router
from app.routes.policy_provider_routes import router as policy_provider_router

app = FastAPI(title="OASYS Backend", version="0.1.0")

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


@app.get("/health")
def health_check():
    return {"status": "ok"}

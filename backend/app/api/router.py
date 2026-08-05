from fastapi import APIRouter

from app.api import audit_runs, documents, health, reviews

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(audit_runs.router, prefix="/audit-runs", tags=["audit-runs"])

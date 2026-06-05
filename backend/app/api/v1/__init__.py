"""API v1 — single router tree for all REST endpoints."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.editor import router as editor_router
from app.api.v1.novels import router as novel_router
from app.api.v1.scripts import router as scripts_router
from app.api.v1.tasks import router as tasks_router

router = APIRouter(prefix="/api/v1", tags=["API v1"])

router.include_router(auth_router)
router.include_router(editor_router)
router.include_router(novel_router)
router.include_router(scripts_router)
router.include_router(tasks_router)

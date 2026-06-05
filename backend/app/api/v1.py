import logging

from fastapi import APIRouter

from app.api.editor import router as editor_router

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["API v1"],
)

router.include_router(editor_router)

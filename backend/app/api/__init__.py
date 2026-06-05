from app.api.v1 import router as api_v1_router
from app.api.tasks import router as tasks_router

__all__ = [
    "api_v1_router",
    "tasks_router",
]

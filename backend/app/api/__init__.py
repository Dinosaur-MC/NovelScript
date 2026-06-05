from app.api.v1 import router as api_v1_router
from app.api.auth import router as auth_router

__all__ = [
    "api_v1_router",
    "auth_router",
]

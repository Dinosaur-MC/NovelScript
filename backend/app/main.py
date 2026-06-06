from starlette.exceptions import HTTPException
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from app.models.http import BaseResponse, ErrorResponse

# 配置日志
logging.basicConfig(
    level=logging.DEBUG, format="[%(asctime)s] %(name)s - %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ========== 创建主应用实例 ==========
app = FastAPI(
    title="NovelScript API",
    description="NovelScript (析幕) — AI 驱动的长篇小说到结构化剧本转换系统",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    debug=True,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"HTTP 异常：{str(exc)}", exc_info=True)
    import traceback
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            code=exc.status_code,
            message=exc.detail,
            detail=traceback.format_exc() if app.debug else None,
        ).model_dump(exclude_none=True),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常：{str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            code=500,
            message="Internal Server Error",
            detail=str(exc) if app.debug else None,
        ).model_dump(exclude_none=True),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== 路由注册 ==========
from app.api import api_v1_router

app.include_router(api_v1_router)


@app.get("/health", tags=["Health"])
async def health_check():
    return BaseResponse(code=200, message="健康检查通过", data={"status": "healthy"})


@app.head("/", tags=["Root"])
async def root_head():
    return Response()

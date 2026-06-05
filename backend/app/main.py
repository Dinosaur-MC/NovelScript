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


# ========== 全局异常处理器 ==========
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常处理器 - 将 HTTPException 转换为统一的 ErrorResponse 格式"""
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
    """通用异常处理器 - 捕获所有未处理的异常"""
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


# ========== 导入并注册各版本 API 路由 ==========
from app.api import api_v1_router, auth_router
from app.api.novel import router as novel_router
from app.api.scripts import router as scripts_router
from app.api.tasks import router as tasks_router
from app.api.editor import router as editor_router

app.include_router(api_v1_router)
app.include_router(auth_router)
app.include_router(novel_router)
app.include_router(scripts_router)
app.include_router(tasks_router)
app.include_router(editor_router)


# ========== 健康检查端点 ==========
@app.get("/health", tags=["Health"])
async def health_check():
    """健康检查"""
    return BaseResponse(code=0, message="健康检查通过", data={"status": "healthy"})


@app.head("/", tags=["Root"])
async def root_head():
    """根路径 HEAD 请求 - 返回响应头"""
    return Response()

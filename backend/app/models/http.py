from pydantic import BaseModel, Field
from typing import Optional


# ========== 基础响应模型 ==========
class BaseResponse(BaseModel):
    """基础响应模型"""

    code: int = Field(200, description="状态码")
    message: str = Field("请求成功", description="响应消息")
    data: Optional[dict] = Field(None, description="响应数据")


# ========== 错误响应 ==========
class ErrorResponse(BaseModel):
    """错误响应模型"""

    code: int = Field(400, description="错误码")
    message: str = Field(description="错误信息")
    detail: Optional[str] = Field(None, description="详细错误信息")

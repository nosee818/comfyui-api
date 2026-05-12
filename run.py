"""启动脚本"""
import uvicorn
from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.gateway_host,
        port=settings.gateway_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )

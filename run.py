"""启动脚本"""
import argparse
import uvicorn
from app.config import settings

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ComfyUI API Gateway")
    parser.add_argument("--port", type=int, default=settings.gateway_port,
                        help=f"服务端口 (默认: {settings.gateway_port})")
    parser.add_argument("--host", type=str, default=settings.gateway_host,
                        help=f"绑定地址 (默认: {settings.gateway_host})")
    parser.add_argument("--log-level", type=str, default=settings.log_level,
                        choices=["debug", "info", "warning", "error"],
                        help=f"日志级别 (默认: {settings.log_level})")
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level=args.log_level.lower(),
    )

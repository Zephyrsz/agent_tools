from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 TubeSafe 本地下载工具")
    parser.add_argument("--port", type=int, default=8765, help="本机监听端口，默认 8765")
    parser.add_argument("--reload", action="store_true", help="开发时自动重载")
    args = parser.parse_args()
    print(f"TubeSafe: http://127.0.0.1:{args.port}")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=args.port,
        reload=args.reload,
        access_log=False,
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse

import uvicorn

from .app import create_app
from .config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="powersite-autonomy")
    parser.add_argument("--config", default="config.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="run the HTTP service and forecast scheduler")
    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.command == "serve":
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

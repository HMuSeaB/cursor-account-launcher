"""python -m bot_gateway"""

from __future__ import annotations

import argparse

from .server import STREAM_PATH, serve_forever


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="本地 Bot 网关。provision=领票+挂路由；默认=监听转发。"
    )
    parser.add_argument("--host", default=None, help="默认 127.0.0.1 / BOT_GATEWAY_HOST")
    parser.add_argument("--port", type=int, default=None, help="默认 8765 / BOT_GATEWAY_PORT")
    parser.add_argument(
        "--print-path",
        action="store_true",
        help="只打印 Stream 路径后退出",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=("serve", "provision"),
        help="serve=监听；provision=领票并尽量在 Box 挂 /sand-stream-relay",
    )
    args = parser.parse_args(argv)
    if args.print_path:
        print(STREAM_PATH)
        return 0
    if args.command == "provision":
        from .box_mount import provision_and_mount
        from .provision import ProvisionError

        try:
            result = provision_and_mount(log=print)
        except ProvisionError as exc:
            print(f"provision 失败：{exc}")
            return 1
        print(result.get("note") or "ok")
        return 0 if result.get("ok") else 1
    serve_forever(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

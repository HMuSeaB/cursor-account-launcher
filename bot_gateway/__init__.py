"""本地 Bot 网关骨架（路②）。

对齐 v136 ``grok-box-relay.json`` 契约：本机监听 Stream 路径，
有 upstream 则透传，无则返回明确 503。不写 Cursor、不跑 EnsureSandBox。
"""

from __future__ import annotations

__version__ = "0.1.0-skeleton"

#!/usr/bin/env python3
"""
MiaoWallet MCP Server for OpenClaw
使用官方 MCP Python SDK
"""

import json
import keyring
from mcp.server.fastmcp import FastMCP

SERVICE_ID = "openclaw_bot"
REGISTRY_KEY = "__wallet_registry__"

mcp = FastMCP("openclaw_bot")


def get_registry() -> list:
    data = keyring.get_password(SERVICE_ID, REGISTRY_KEY)
    if not data:
        return []
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return []


@mcp.tool()
def list_wallets() -> str:
    """列出所有已注册的钱包别名和状态"""
    wallets = get_registry()
    if not wallets:
        return "📭 没有注册任何钱包。\n请让用户运行: python3 wallet_panel.py add"

    lines = [f"🔐 已注册 {len(wallets)} 个钱包:\n"]
    for w in wallets:
        pk = keyring.get_password(SERVICE_ID, w)
        status = "✅ 可用" if pk else "❌ 不可用"
        preview = f"[{pk[:4]}...]" if pk else ""
        lines.append(f"  • {w} — {status} {preview}")
    return "\n".join(lines)


@mcp.tool()
def wallet_status(alias: str) -> str:
    """查看指定钱包的详细状态

    Args:
        alias: 钱包别名 (如 sui_main, eth_dev)
    """
    pk = keyring.get_password(SERVICE_ID, alias)
    if pk:
        return (
            f"🔐 钱包: {alias}\n"
            f"状态: ✅ 可用\n"
            f"前缀: {pk[:6]}...\n"
            f"长度: {len(pk)} 字符"
        )
    return f"❌ 钱包 '{alias}' 不存在或无法访问"


@mcp.tool()
def sign_or_use_key(alias: str, purpose: str) -> str:
    """获取私钥用于签名操作。私钥在返回后立即从服务端内存清除。
    调用者（agent）必须在使用后立即丢弃，不得存储、打印或记录私钥。

    Args:
        alias: 钱包别名
        purpose: 用途说明（如 "签名交易", "导出备份"）
    """
    pk = keyring.get_password(SERVICE_ID, alias)
    if pk:
        result = pk
        # 立即清除本地引用
        pk = None  # noqa
        del pk
        return result
    return f"❌ 无法获取钱包 '{alias}' 的私钥"


if __name__ == "__main__":
    mcp.run(transport="stdio")

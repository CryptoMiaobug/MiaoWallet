#!/usr/bin/env python3
"""
MiaoWallet MCP Server for OpenClaw
通过 Bridge API (localhost:3847) 操作钱包，不暴露私钥
"""

import json
import httpx
from mcp.server.fastmcp import FastMCP

BRIDGE_URL = "http://127.0.0.1:3847"
SUI_RPC = "https://fullnode.mainnet.sui.io:443"

mcp = FastMCP("miaowallet")


def bridge_get(path: str) -> dict:
    """调 bridge GET 接口"""
    try:
        r = httpx.get(f"{BRIDGE_URL}{path}", timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def bridge_post(path: str, data: dict = None) -> dict:
    """调 bridge POST 接口"""
    try:
        r = httpx.post(f"{BRIDGE_URL}{path}", json=data or {}, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def sui_rpc(method: str, params: list = None) -> dict:
    """调 Sui JSON-RPC"""
    try:
        r = httpx.post(SUI_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_address() -> str:
    """获取当前连接的 Sui 钱包地址和公钥"""
    data = bridge_get("/address")
    if "error" in data:
        return f"❌ {data['error']}\n提示：请先在 WebGUI 中连接 DApp"
    addr = data.get("address", "?")
    network = data.get("network", "?")
    return f"🔐 地址: {addr}\n🌐 网络: {network}"


@mcp.tool()
def get_balance(coin_type: str = "0x2::sui::SUI") -> str:
    """查询当前钱包的代币余额

    Args:
        coin_type: 代币类型，默认 SUI。USDC 用 0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC
    """
    # 先获取地址
    addr_data = bridge_get("/address")
    if "error" in addr_data:
        return f"❌ {addr_data['error']}\n提示：请先在 WebGUI 中连接 DApp"
    
    address = addr_data["address"]
    network = addr_data.get("network", "mainnet")
    
    # 根据网络选 RPC
    rpc_url = f"https://fullnode.{network}.sui.io:443"
    
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "suix_getBalance",
            "params": [address, coin_type]
        }, timeout=10)
        result = r.json()
    except Exception as e:
        return f"❌ RPC 调用失败: {e}"
    
    if "error" in result:
        return f"❌ {result['error']}"
    
    balance_data = result.get("result", {})
    total = int(balance_data.get("totalBalance", "0"))
    
    # SUI 是 9 位小数，USDC 是 6 位
    if "sui::SUI" in coin_type:
        human = total / 1_000_000_000
        symbol = "SUI"
    elif "usdc::USDC" in coin_type:
        human = total / 1_000_000
        symbol = "USDC"
    else:
        human = total
        symbol = coin_type.split("::")[-1] if "::" in coin_type else "?"
    
    return f"💰 {human:.4f} {symbol}\n📍 {address[:10]}...{address[-6:]}\n🌐 {network}"


@mcp.tool()
def get_session_status() -> str:
    """查看当前 DApp 签名会话的状态"""
    data = bridge_get("/session")
    if "error" in data:
        return f"❌ {data['error']}"
    
    if not data.get("active", False):
        return "⚠️ 没有活跃的签名会话\n提示：请在 WebGUI 中连接 DApp"
    
    addr = data.get("address", "?")
    sign_count = data.get("signCount", 0)
    max_signs = data.get("maxSigns", 0)
    elapsed = data.get("elapsedSeconds", 0)
    max_time = data.get("maxTimeSeconds", 0)
    wallet = data.get("wallet", "?")
    
    lines = [
        f"✅ 会话活跃",
        f"🔐 钱包: {wallet}",
        f"📍 地址: {addr[:10]}...{addr[-6:]}",
        f"✍️ 已签名: {sign_count} 次",
    ]
    if max_signs > 0:
        lines.append(f"📊 签名上限: {max_signs} 次（剩余 {max_signs - sign_count}）")
    else:
        lines.append(f"📊 签名上限: 无限制")
    
    lines.append(f"⏱ 已运行: {elapsed // 60} 分钟")
    if max_time > 0:
        remaining = max(0, (max_time - elapsed) // 60)
        lines.append(f"⏳ 时间限制: {max_time // 60} 分钟（剩余 {remaining} 分钟）")
    
    return "\n".join(lines)


@mcp.tool()
def list_wallets() -> str:
    """列出所有已保存的钱包"""
    import os
    wallet_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".wallet_addresses.json")
    
    if not os.path.exists(wallet_file):
        return "📭 没有钱包，请在 WebGUI 中添加"
    
    try:
        with open(wallet_file, 'r') as f:
            raw = json.load(f)
    except Exception as e:
        return f"❌ 读取钱包文件失败: {e}"
    
    if not raw:
        return "📭 没有钱包，请在 WebGUI 中添加"
    
    # 按钱包名分组
    wallets = {}
    suffixes = ["_sui", "_solana", "_ethereum"]
    for key, addr in raw.items():
        name = key
        chain = "?"
        for s in suffixes:
            if key.endswith(s):
                name = key[:-len(s)]
                chain = s[1:].upper()
                if chain == "ETHEREUM":
                    chain = "ETH"
                break
        if name not in wallets:
            wallets[name] = {}
        wallets[name][chain] = addr
    
    lines = [f"🔐 共 {len(wallets)} 个钱包:\n"]
    for name, chains in wallets.items():
        lines.append(f"📁 {name}")
        for chain, addr in chains.items():
            lines.append(f"  {chain}: {addr[:10]}...{addr[-6:]}")
    
    return "\n".join(lines)


@mcp.tool()
def sign_transaction(tx_bytes_base64: str) -> str:
    """签名一笔 Sui 交易（base64 编码的交易 bytes）

    Args:
        tx_bytes_base64: base64 编码的交易数据
    """
    data = bridge_post("/sign-raw", {"txBytes": tx_bytes_base64})
    if "error" in data:
        return f"❌ 签名失败: {data['error']}"
    
    return f"✅ 签名成功\n📝 signature: {data.get('signature', '?')}"


def resolve_suins(name: str, rpc_url: str) -> str | None:
    """解析 SuiNS 域名（如 bvlgari.sui）为 Sui 地址"""
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "suix_resolveNameServiceAddress",
            "params": [name]
        }, timeout=10)
        result = r.json().get("result")
        return result if result else None
    except:
        return None


@mcp.tool()
def transfer_sui(to: str, amount: float) -> str:
    """转 SUI 到指定地址

    Args:
        to: 接收方 Sui 地址（0x 开头）或 SuiNS 域名（如 bvlgari.sui）
        amount: 转账金额（单位 SUI，如 0.5）
    """
    # 获取当前地址和网络
    addr_data = bridge_get("/address")
    if "error" in addr_data:
        return f"❌ {addr_data['error']}\n提示：请先连接 DApp"
    
    address = addr_data["address"]
    network = addr_data.get("network", "mainnet")
    rpc_url = f"https://fullnode.{network}.sui.io:443"
    amount_mist = int(amount * 1_000_000_000)

    # SuiNS 域名解析
    suins_name = None
    if not to.startswith("0x"):
        suins_name = to if to.endswith(".sui") else to + ".sui"
        resolved = resolve_suins(suins_name, rpc_url)
        if not resolved:
            return f"❌ 无法解析 SuiNS 域名: {suins_name}"
        to = resolved
    
    # 1. 获取 gas coin
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "suix_getCoins",
            "params": [address, "0x2::sui::SUI", None, 1]
        }, timeout=10)
        coins = r.json().get("result", {}).get("data", [])
        if not coins:
            return "❌ 没有 SUI coin 可用"
        gas_coin = coins[0]["coinObjectId"]
    except Exception as e:
        return f"❌ 获取 coin 失败: {e}"
    
    # 2. 构建交易（unsafe_transferSui）
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "unsafe_transferSui",
            "params": [address, gas_coin, "2000000", to, str(amount_mist)]
        }, timeout=10)
        result = r.json()
        if "error" in result:
            return f"❌ 构建交易失败: {result['error']}"
        tx_bytes = result["result"]["txBytes"]
    except Exception as e:
        return f"❌ 构建交易失败: {e}"
    
    # 3. 签名
    sign_data = bridge_post("/sign-raw", {"txBytes": tx_bytes})
    if "error" in sign_data:
        return f"❌ 签名失败: {sign_data['error']}"
    
    signature = sign_data["signature"]
    
    # 4. 提交交易
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "sui_executeTransactionBlock",
            "params": [tx_bytes, [signature], {"showEffects": True}, "WaitForLocalExecution"]
        }, timeout=30)
        exec_result = r.json()
        if "error" in exec_result:
            return f"❌ 提交失败: {exec_result['error']}"
        
        effects = exec_result.get("result", {}).get("effects", {})
        status = effects.get("status", {}).get("status", "?")
        digest = exec_result.get("result", {}).get("digest", "?")
        
        if status == "success":
            to_display = suins_name if suins_name else f"{to[:10]}...{to[-6:]}"
            return f"✅ 转账成功！\n💸 {amount} SUI → {to_display}\n🔗 tx: {digest}"
        else:
            return f"❌ 交易失败: {status}\n🔗 tx: {digest}"
    except Exception as e:
        return f"❌ 提交交易失败: {e}"


@mcp.tool()
def transfer_coin(to: str, amount: float, coin_type: str, decimals: int = 6) -> str:
    """转任意代币到指定地址（如 USDC）

    Args:
        to: 接收方 Sui 地址（0x 开头）
        amount: 转账金额（人类可读，如 10.5）
        coin_type: 代币类型，如 0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC
        decimals: 小数位数，USDC 为 6，SUI 为 9
    """
    addr_data = bridge_get("/address")
    if "error" in addr_data:
        return f"❌ {addr_data['error']}\n提示：请先连接 DApp"
    
    address = addr_data["address"]
    network = addr_data.get("network", "mainnet")
    rpc_url = f"https://fullnode.{network}.sui.io:443"
    amount_raw = int(amount * (10 ** decimals))
    
    # 1. 获取该代币的 coins
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "suix_getCoins",
            "params": [address, coin_type, None, 50]
        }, timeout=10)
        coins = r.json().get("result", {}).get("data", [])
        if not coins:
            return f"❌ 没有 {coin_type.split('::')[-1]} 可用"
    except Exception as e:
        return f"❌ 获取 coin 失败: {e}"
    
    # 找到足够金额的 coin
    coin_id = None
    for c in coins:
        if int(c.get("balance", "0")) >= amount_raw:
            coin_id = c["coinObjectId"]
            break
    
    if not coin_id:
        # 余额不够或需要合并
        total = sum(int(c.get("balance", "0")) for c in coins)
        symbol = coin_type.split("::")[-1]
        return f"❌ 单个 coin 余额不足，需要合并\n总余额: {total / (10 ** decimals):.4f} {symbol}"
    
    # 2. 获取 gas coin（SUI）
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "suix_getCoins",
            "params": [address, "0x2::sui::SUI", None, 1]
        }, timeout=10)
        gas_coins = r.json().get("result", {}).get("data", [])
        if not gas_coins:
            return "❌ 没有 SUI 支付 gas"
        gas_coin = gas_coins[0]["coinObjectId"]
    except Exception as e:
        return f"❌ 获取 gas coin 失败: {e}"
    
    # 3. 构建交易（unsafe_transferObject 或 moveCall pay）
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "unsafe_pay",
            "params": [address, [coin_id], [to], [str(amount_raw)], gas_coin, "2000000"]
        }, timeout=10)
        result = r.json()
        if "error" in result:
            return f"❌ 构建交易失败: {result['error']}"
        tx_bytes = result["result"]["txBytes"]
    except Exception as e:
        return f"❌ 构建交易失败: {e}"
    
    # 4. 签名
    sign_data = bridge_post("/sign-raw", {"txBytes": tx_bytes})
    if "error" in sign_data:
        return f"❌ 签名失败: {sign_data['error']}"
    
    signature = sign_data["signature"]
    
    # 5. 提交
    try:
        r = httpx.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "sui_executeTransactionBlock",
            "params": [tx_bytes, [signature], {"showEffects": True}, "WaitForLocalExecution"]
        }, timeout=30)
        exec_result = r.json()
        if "error" in exec_result:
            return f"❌ 提交失败: {exec_result['error']}"
        
        effects = exec_result.get("result", {}).get("effects", {})
        status = effects.get("status", {}).get("status", "?")
        digest = exec_result.get("result", {}).get("digest", "?")
        symbol = coin_type.split("::")[-1]
        
        if status == "success":
            return f"✅ 转账成功！\n💸 {amount} {symbol} → {to[:10]}...{to[-6:]}\n🔗 tx: {digest}"
        else:
            return f"❌ 交易失败: {status}\n🔗 tx: {digest}"
    except Exception as e:
        return f"❌ 提交交易失败: {e}"


@mcp.tool()
def store_attestation(tx_digest: str, from_addr: str, to_addr: str, amount: str, coin_type: str = "SUI", memo: str = "") -> str:
    """将交易记录存证到 Walrus 去中心化存储

    Args:
        tx_digest: 交易哈希（Sui tx digest）
        from_addr: 发送方地址
        to_addr: 接收方地址
        amount: 转账金额（人类可读，如 "0.1 SUI"）
        coin_type: 代币类型，默认 SUI
        memo: 备注信息（可选）
    """
    import subprocess
    import tempfile
    import time

    # 构建存证 JSON
    attestation = {
        "version": "1.0",
        "type": "transfer_attestation",
        "chain": "sui",
        "tx_digest": tx_digest,
        "from": from_addr,
        "to": to_addr,
        "amount": amount,
        "coin_type": coin_type,
        "memo": memo,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "wallet": "MiaoWallet",
    }

    # 写临时文件
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(attestation, f, ensure_ascii=False, indent=2)
            tmp_path = f.name
    except Exception as e:
        return f"❌ 创建临时文件失败: {e}"

    # 调 walrus CLI 存储
    try:
        result = subprocess.run(
            ["walrus", "store", "--context", "mainnet", "--epochs", "53", tmp_path],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout + result.stderr

        # 解析 blob ID
        blob_id = None
        object_id = None
        for line in output.split('\n'):
            if 'Blob ID:' in line:
                blob_id = line.split('Blob ID:')[1].strip()
            elif 'Object ID:' in line:
                object_id = line.split('Object ID:')[1].strip()

        if not blob_id:
            return f"❌ 存储失败，未获取到 Blob ID\n输出: {output[-500:]}"

        lines = [
            f"✅ 存证成功！",
            f"📦 Blob ID: {blob_id}",
        ]
        if object_id:
            lines.append(f"🆔 Object ID: {object_id}")
            lines.append(f"🔍 https://suiscan.xyz/mainnet/object/{object_id}")
        lines += [
            f"🔗 TX: {tx_digest}",
            f"💸 {amount} {coin_type}: {from_addr[:10]}... → {to_addr[:10]}...",
            f"📖 读取: walrus read --context mainnet {blob_id}",
            f"🌐 https://walruscan.com/mainnet/blob/{blob_id}",
        ]
        return "\n".join(lines)

    except subprocess.TimeoutExpired:
        return "❌ 存储超时（120s）"
    except Exception as e:
        return f"❌ 存储失败: {e}"
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except:
            pass


@mcp.tool()
def read_attestation(blob_id: str) -> str:
    """从 Walrus 读取存证记录

    Args:
        blob_id: Walrus Blob ID
    """
    import subprocess

    try:
        result = subprocess.run(
            ["walrus", "read", "--context", "mainnet", blob_id],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout + result.stderr

        # 尝试从输出中提取 JSON（最后一行通常是内容）
        lines = output.strip().split('\n')
        # 找 JSON 内容
        for line in reversed(lines):
            line = line.strip()
            if line.startswith('{'):
                try:
                    data = json.loads(line)
                    parts = [f"📋 存证记录:"]
                    parts.append(f"  🔗 TX: {data.get('tx_digest', '?')}")
                    parts.append(f"  💸 {data.get('amount', '?')} {data.get('coin_type', '?')}")
                    parts.append(f"  📤 From: {data.get('from', '?')}")
                    parts.append(f"  📥 To: {data.get('to', '?')}")
                    parts.append(f"  ⏰ 时间: {data.get('timestamp', '?')}")
                    parts.append(f"  🏷 钱包: {data.get('wallet', '?')}")
                    if data.get('memo'):
                        parts.append(f"  📝 备注: {data['memo']}")
                    return "\n".join(parts)
                except json.JSONDecodeError:
                    pass

        return f"📄 原始内容:\n{lines[-1] if lines else '(空)'}"

    except subprocess.TimeoutExpired:
        return "❌ 读取超时（30s）"
    except Exception as e:
        return f"❌ 读取失败: {e}"


@mcp.tool()
def swap_token(from_coin: str, to_coin: str, amount: float, slippage: float = 1.0) -> str:
    """通过 Cetus 聚合器兑换代币（自动找最优路由，支持 30+ DEX）

    Args:
        from_coin: 源代币符号（SUI / WAL / USDC / CETUS）
        to_coin: 目标代币符号（SUI / WAL / USDC / CETUS）
        amount: 兑换金额（人类可读，如 0.5）
        slippage: 滑点百分比，默认 1%
    """
    import subprocess
    import os

    swap_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cetus-swap", "swap.mjs")
    if not os.path.exists(swap_script):
        return "❌ swap 脚本不存在，请先安装 cetus-swap"

    try:
        result = subprocess.run(
            ["node", swap_script, from_coin, to_coin, str(amount), str(slippage)],
            capture_output=True, text=True, timeout=120,
            cwd=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cetus-swap")
        )
        output = result.stdout + result.stderr

        if result.returncode != 0:
            # 提取错误信息
            for line in output.strip().split('\n'):
                if '❌' in line:
                    return line
            return f"❌ Swap 失败\n{output[-500:]}"

        # 提取关键信息
        lines = []
        for line in output.strip().split('\n'):
            if any(k in line for k in ['✅', '💸', '🔗', '💰', '📊', '🛡', '+', '-']):
                lines.append(line)
        return "\n".join(lines) if lines else output[-500:]

    except subprocess.TimeoutExpired:
        return "❌ Swap 超时（120s）"
    except Exception as e:
        return f"❌ Swap 失败: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")

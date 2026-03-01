#!/usr/bin/env python3
"""
安全的 SUI 转账脚本（带 Dry Run 预览）
- 私钥从 macOS Keychain 获取（需弹窗授权）
- 签名前模拟交易，显示资产变化和 Gas 预估
- 支持交互确认 / --yes 跳过确认（供 bot 调用）
- 用完立即清除内存
"""

import json
import sys
import os
import hashlib
import base64

try:
    import keyring
    import bech32
    from nacl.signing import SigningKey
    import requests
except ImportError as e:
    print(f"❌ 缺少依赖: {e}")
    print("运行: pip install keyring pynacl bech32 requests")
    sys.exit(1)

SERVICE_ID = "openclaw_bot"
SUI_RPC = "https://fullnode.mainnet.sui.io:443"

# ─── SuiNS 解析 ───────────────────────────────────────────────

def resolve_suins(name: str) -> str:
    """解析 .sui 域名为地址，失败则返回 None"""
    try:
        result = rpc_call("suix_resolveNameServiceAddress", [name])
        return result
    except Exception:
        return None

# ─── 基础工具 ──────────────────────────────────────────────────

def get_address_from_key(privkey_bech32: str) -> tuple:
    """返回 (seed_bytes, scheme, pk_bytes, address_hex)"""
    hrp, data5bit = bech32.bech32_decode(privkey_bech32)
    data8bit = bytes(bech32.convertbits(data5bit, 5, 8, False))
    scheme = data8bit[0]
    seed = data8bit[1:33]

    sk = SigningKey(seed)
    pk = sk.verify_key.encode()

    hasher = hashlib.blake2b(digest_size=32)
    hasher.update(bytes([scheme]) + pk)
    address = "0x" + hasher.hexdigest()

    return seed, scheme, pk, address


def rpc_call(method: str, params: list):
    """调用 Sui JSON-RPC"""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(SUI_RPC, json=payload, timeout=15)
    result = r.json()
    if "error" in result:
        raise Exception(f"RPC error: {result['error']}")
    return result["result"]


def get_coins(address: str):
    """获取地址的 SUI coins"""
    return rpc_call("suix_getCoins", [address, "0x2::sui::SUI", None, 10])


def build_transfer_tx(sender: str, recipient: str, amount: int, coin_id: str, gas_budget: int):
    """构建转账交易（不签名）"""
    result = rpc_call("unsafe_paySui", [
        sender,
        [coin_id],
        [recipient],
        [str(amount)],
        str(gas_budget)
    ])
    return result


# ─── Dry Run 模拟 ─────────────────────────────────────────────

def dry_run(tx_bytes_b64: str) -> dict:
    """模拟交易，返回预估结果"""
    return rpc_call("sui_dryRunTransactionBlock", [tx_bytes_b64])


def print_dry_run(result: dict, sender: str, recipient: str, amount_sui: float):
    """格式化显示 Dry Run 结果"""
    effects = result.get("effects", {})
    status = effects.get("status", {}).get("status", "unknown")

    gas = effects.get("gasUsed", {})
    computation = int(gas.get("computationCost", 0))
    storage = int(gas.get("storageCost", 0))
    rebate = int(gas.get("storageRebate", 0))
    gas_total = computation + storage - rebate

    print("\n" + "=" * 55)
    print("  📋 交易预览 (Dry Run 模拟)")
    print("=" * 55)

    # 模拟状态
    if status == "success":
        print(f"  ✅ 模拟状态: 成功")
    else:
        failure = effects.get("status", {}).get("error", "")
        print(f"  ❌ 模拟状态: 失败 — {failure}")
        return False

    # 资产变化
    balance_changes = result.get("balanceChanges", [])
    if balance_changes:
        print(f"\n  💰 资产变化:")
        for bc in balance_changes:
            owner = bc.get("owner", {})
            addr = owner.get("AddressOwner", "?")
            amt = int(bc.get("amount", 0))
            coin_type = bc.get("coinType", "")
            # 简化 coin type 显示
            coin_short = coin_type.split("::")[-1] if "::" in coin_type else coin_type

            # 标记身份
            if addr == sender:
                label = "你 (发送方)"
            elif addr == recipient:
                label = "收款方"
            else:
                label = addr[:10] + "..." + addr[-4:]

            sign = "+" if amt > 0 else ""
            print(f"     {label}: {sign}{amt / 1e9:.9g} {coin_short}")

    # Gas 费用
    print(f"\n  ⛽ Gas 预估:")
    print(f"     计算费: {computation / 1e9:.9g} SUI")
    print(f"     存储费: {storage / 1e9:.9g} SUI")
    print(f"     存储返还: -{rebate / 1e9:.9g} SUI")
    print(f"     总计: {gas_total / 1e9:.9g} SUI")

    # 实际到账
    print(f"\n  📨 转账摘要:")
    print(f"     发送: {amount_sui} SUI")
    print(f"     Gas:  ~{gas_total / 1e9:.6f} SUI")
    print(f"     总支出: ~{(amount_sui * 1e9 + gas_total) / 1e9:.6f} SUI")

    print("=" * 55)
    return True


# ─── 签名执行 ─────────────────────────────────────────────────

def sign_and_execute(tx_bytes_b64: str, seed: bytes, scheme: int):
    """签名并执行交易"""
    tx_bytes = base64.b64decode(tx_bytes_b64)

    intent_prefix = bytes([0, 0, 0])
    intent_msg = intent_prefix + tx_bytes

    hasher = hashlib.blake2b(digest_size=32)
    hasher.update(intent_msg)
    digest = hasher.digest()

    sk = SigningKey(seed)
    signature = sk.sign(digest).signature
    pk = sk.verify_key.encode()

    sig_bytes = bytes([scheme]) + signature + pk
    sig_b64 = base64.b64encode(sig_bytes).decode()

    result = rpc_call("sui_executeTransactionBlock", [
        tx_bytes_b64,
        [sig_b64],
        {"showEffects": True, "showBalanceChanges": True},
        "WaitForLocalExecution"
    ])
    return result


# ─── 主流程 ───────────────────────────────────────────────────

def transfer(wallet_alias: str, recipient: str, amount_sui: float, auto_confirm: bool = False):
    """执行转账（带 Dry Run 预览）"""
    amount_mist = int(amount_sui * 1_000_000_000)

    # 解析 .sui 域名
    original_recipient = recipient
    if recipient.endswith(".sui"):
        print(f"\n🔍 解析 SuiNS 域名: {recipient}")
        resolved = resolve_suins(recipient)
        if not resolved:
            print(f"❌ 无法解析域名 {recipient}")
            return None
        recipient = resolved
        print(f"   → {recipient}")

    print(f"\n📤 转账请求")
    print(f"   钱包: {wallet_alias}")
    print(f"   收款: {original_recipient}")
    if original_recipient != recipient:
        print(f"   地址: {recipient}")
    print(f"   金额: {amount_sui} SUI ({amount_mist} MIST)")
    print(f"\n🔐 正在请求 Keychain 授权...")

    # 从 Keychain 获取私钥
    privkey = keyring.get_password(SERVICE_ID, wallet_alias)
    if not privkey:
        print("❌ 无法获取私钥（用户拒绝或钱包不存在）")
        return None

    try:
        seed, scheme, pk, sender = get_address_from_key(privkey)
        save_wallet_address(wallet_alias, sender)  # 缓存地址供 dry-run 使用
        print(f"   发送方: {sender}")

        # 获取 coins
        coins = get_coins(sender)
        if not coins["data"]:
            print("❌ 没有可用的 SUI coin")
            return None

        coin = coins["data"][0]
        coin_id = coin["coinObjectId"]
        balance = int(coin.get("balance", 0))
        print(f"   余额: {balance / 1e9:.9g} SUI (主 coin)")

        # 构建交易
        print("\n⏳ 构建交易中...")
        tx_result = build_transfer_tx(sender, recipient, amount_mist, coin_id, 5_000_000)
        tx_bytes = tx_result["txBytes"]

        # ★ Dry Run 模拟 ★
        print("⏳ Dry Run 模拟中...")
        dry_result = dry_run(tx_bytes)
        ok = print_dry_run(dry_result, sender, recipient, amount_sui)

        if not ok:
            print("\n🚫 模拟失败，交易已取消")
            return None

        # 确认
        if not auto_confirm:
            ans = input("\n❓ 确认执行? (y/N): ").strip().lower()
            if ans not in ("y", "yes"):
                print("🚫 用户取消")
                return None
        else:
            print("\n⚡ 自动确认模式 (--yes)")

        # 签名执行
        print("\n✍️  签名并发送中...")
        result = sign_and_execute(tx_bytes, seed, scheme)

        # 最终结果
        effects = result.get("effects", {})
        status = effects.get("status", {}).get("status", "unknown")
        digest = result.get("digest", "unknown")

        gas = effects.get("gasUsed", {})
        gas_total = (int(gas.get("computationCost", 0)) +
                     int(gas.get("storageCost", 0)) -
                     int(gas.get("storageRebate", 0)))

        print(f"\n{'✅' if status == 'success' else '❌'} 最终状态: {status}")
        print(f"   交易哈希: {digest}")
        print(f"   Gas 实际: {gas_total / 1e9:.6f} SUI")
        print(f"   浏览器: https://suiscan.xyz/mainnet/tx/{digest}")

        for bc in result.get("balanceChanges", []):
            addr = bc["owner"].get("AddressOwner", "?")
            short = addr[:8] + "..." + addr[-4:]
            amt = int(bc["amount"])
            print(f"   {short}: {amt / 1e9:+.9g} SUI")

        return result

    finally:
        privkey = None
        seed = None
        del privkey, seed
        print("\n🗑️  私钥已从内存清除")


# ─── 仅 Dry Run ──────────────────────────────────────────────

def get_wallet_address(wallet_alias: str) -> str:
    """从钱包注册表获取地址（不需要私钥）"""
    # 先尝试从 wallet_panel 读取地址
    try:
        import subprocess as sp
        result = sp.run(
            [sys.executable, "wallet_panel.py", "list", "--json"],
            capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__))
        )
        if result.returncode == 0:
            wallets = json.loads(result.stdout)
            for w in wallets:
                if w.get("alias") == wallet_alias:
                    return w["address"]
    except Exception:
        pass

    # 备用：用 security 命令非交互式读取地址映射文件
    addr_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".wallet_addresses.json")
    if os.path.exists(addr_file):
        with open(addr_file) as f:
            addrs = json.loads(f.read())
            if wallet_alias in addrs:
                return addrs[wallet_alias]

    return None


def save_wallet_address(wallet_alias: str, address: str):
    """缓存钱包地址到本地文件（不含私钥，安全）"""
    addr_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".wallet_addresses.json")
    addrs = {}
    if os.path.exists(addr_file):
        with open(addr_file) as f:
            addrs = json.loads(f.read())
    addrs[wallet_alias] = address
    with open(addr_file, "w") as f:
        f.write(json.dumps(addrs, indent=2))


def dry_run_only(wallet_alias: str, recipient: str, amount_sui: float):
    """只做模拟预览，不签名不执行。不需要 Keychain 授权。"""
    amount_mist = int(amount_sui * 1_000_000_000)

    original_recipient = recipient
    if recipient.endswith(".sui"):
        print(f"🔍 解析 SuiNS 域名: {recipient}")
        resolved = resolve_suins(recipient)
        if not resolved:
            print(f"❌ 无法解析域名 {recipient}")
            sys.exit(1)
        recipient = resolved
        print(f"   → {recipient}")

    # 获取发送方地址（不需要私钥）
    sender = get_wallet_address(wallet_alias)
    if not sender:
        print(f"❌ 找不到钱包 {wallet_alias} 的地址")
        print(f"   提示: 首次使用需先执行一次带 --yes 的转账来缓存地址")
        print(f"   或手动创建 .wallet_addresses.json")
        sys.exit(1)

    print(f"\n📤 转账预览 (Dry Run)")
    print(f"   钱包: {wallet_alias}")
    print(f"   发送方: {sender}")
    print(f"   收款: {original_recipient}")
    if original_recipient != recipient:
        print(f"   收款地址: {recipient}")
    print(f"   金额: {amount_sui} SUI ({amount_mist} MIST)")

    # 获取 coins
    coins = get_coins(sender)
    if not coins["data"]:
        print("❌ 没有可用的 SUI coin")
        sys.exit(1)

    coin = coins["data"][0]
    coin_id = coin["coinObjectId"]
    balance = int(coin.get("balance", 0))
    print(f"   当前余额: {balance / 1e9:.9g} SUI")

    # 构建交易
    print("\n⏳ 构建交易中...")
    tx_result = build_transfer_tx(sender, recipient, amount_mist, coin_id, 5_000_000)
    tx_bytes = tx_result["txBytes"]

    # Dry Run 模拟（不需要签名）
    print("⏳ Dry Run 模拟中...")
    dry_result = dry_run(tx_bytes)
    print_dry_run(dry_result, sender, recipient, amount_sui)

    print(f"\n💡 确认后执行: python3 sui_transfer.py {wallet_alias} {original_recipient} {amount_sui} --yes")


# ─── CLI 入口 ─────────────────────────────────────────────────

if __name__ == "__main__":
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    auto = "--yes" in flags
    dry_only = "--dry-run" in flags

    if len(args) != 3:
        print("用法: python3 sui_transfer.py <钱包别名> <收款地址或.sui域名> <金额SUI> [选项]")
        print("选项:")
        print("  --dry-run  只模拟预览，不执行")
        print("  --yes      跳过确认直接执行")
        print("示例:")
        print("  python3 sui_transfer.py sui1 bvlgari.sui 0.01 --dry-run")
        print("  python3 sui_transfer.py sui1 bvlgari.sui 0.01 --yes")
        sys.exit(1)

    if dry_only:
        dry_run_only(args[0], args[1], float(args[2]))
    else:
        transfer(args[0], args[1], float(args[2]), auto_confirm=auto)

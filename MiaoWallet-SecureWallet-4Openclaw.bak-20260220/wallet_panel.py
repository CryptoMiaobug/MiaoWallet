#!/usr/bin/env python3
"""
OpenClaw Wallet Control Panel (MiaoWallet)
Usage:
  python3 wallet_panel.py list          # List wallets
  python3 wallet_panel.py add           # Add wallet
  python3 wallet_panel.py remove <name> # Remove wallet
  python3 wallet_panel.py test <name>   # Test access
  python3 wallet_panel.py reset-acl <name> # Reset ACL
  python3 wallet_panel.py export-config # Export config
"""

import keyring
import getpass
import argparse
import json
import hashlib
import subprocess
import sys
import os
import locale

SERVICE_ID = "openclaw_bot"
REGISTRY_KEY = "__wallet_registry__"

# ── i18n ─────────────────────────────────────────────

STRINGS = {
    "zh": {
        "panel_title": "🔐 MiaoWallet 控制面板",
        "wallet_list": "🔐 OpenClaw 钱包列表 (共 {count} 个)",
        "no_wallets": "📭 还没有注册任何钱包。",
        "no_wallets_hint": "   使用 'python3 wallet_panel.py add' 添加第一个。",
        "address": "地址",
        "no_address": "(无地址)",
        "add_title": "🔐 添加新钱包到 macOS Keychain",
        "alias_prompt": "钱包别名 (如 sui_main, eth_dev): ",
        "invalid_alias": "❌ 无效的别名。",
        "exists_overwrite": "⚠️  '{alias}' 已存在，覆盖？(y/n): ",
        "cancelled": "已取消。",
        "chain_type": "链类型:",
        "chain_other": "其他",
        "chain_select": "选择 (1-4, 默认4): ",
        "paste_key": "粘贴私钥 (不会显示): ",
        "empty_key": "❌ 私钥不能为空。",
        "sui_warn": "⚠️  Sui 私钥通常为 32 或 64 字节，当前 {n} 字节",
        "evm_warn": "⚠️  EVM 私钥通常为 32 字节，当前 {n} 字节",
        "continue_yn": "继续？(y/n): ",
        "derived_addr": "📍 推导地址: {addr}",
        "store_fail": "❌ 存储失败: {err}",
        "store_ok": "✅ 钱包 [{alias}] 已安全存入 Keychain (需密码确认访问)!",
        "remove_confirm": "⚠️  确认删除钱包 '{alias}'？(yes/no): ",
        "remove_not_found": "❌ 钱包 '{alias}' 不存在。",
        "remove_ok": "✅ 钱包 [{alias}] 已删除。",
        "remove_fail": "❌ 删除失败: {err}",
        "test_title": "🔍 测试钱包 '{alias}' 访问...",
        "test_chain": "链: {chain}",
        "test_addr": "地址: {addr}",
        "test_ok": "✅ Keychain 访问成功！长度: {n}",
        "test_fail": "❌ 无法访问 Keychain",
        "test_err": "❌ 错误: {err}",
        "acl_title": "🔒 重置 '{alias}' 的 Keychain 访问控制",
        "acl_desc": "   这将移除所有信任应用（如 Python），恢复每次弹窗授权。",
        "acl_read_fail": "❌ 无法读取私钥，请在 Keychain Access 中手动操作。",
        "acl_fail": "❌ 重置失败: {err}",
        "acl_ok": "✅ '{alias}' 的 ACL 已重置，下次访问将弹窗授权。",
        "export_empty": "📭 没有钱包可导出。",
        "usage_remove": "❌ 用法: wallet_panel.py remove <名称>",
        "usage_test": "❌ 用法: wallet_panel.py test <名称>",
        "usage_acl": "❌ 用法: wallet_panel.py reset-acl <名称>",
        "rename_select_prompt": "🔄 修改钱包昵称",
        "rename_input_hint": "  输入 00 可随时取消",
        "rename_old_alias": "当前钱包别名",
        "rename_new_alias": "新钱包昵称",
        "rename_confirm": "确认将 '{old}' 改名为 '{new}'",
        "rename_success": "✅ 钱包昵称已从 '{old}' 修改为 '{new}'",
        "wallet_not_found": "❌ 钱包 '{alias}' 不存在",
        "alias_already_exists": "❌ 昵称 '{alias}' 已存在",
        "operation_cancelled": "操作已取消",
    },
    "en": {
        "panel_title": "🔐 MiaoWallet Control Panel",
        "wallet_list": "🔐 OpenClaw Wallet List ({count} total)",
        "no_wallets": "📭 No wallets registered yet.",
        "no_wallets_hint": "   Use 'python3 wallet_panel.py add' to add your first one.",
        "address": "Address",
        "no_address": "(no address)",
        "add_title": "🔐 Add New Wallet to macOS Keychain",
        "alias_prompt": "Wallet alias (e.g. sui_main, eth_dev): ",
        "invalid_alias": "❌ Invalid alias.",
        "exists_overwrite": "⚠️  '{alias}' already exists. Overwrite? (y/n): ",
        "cancelled": "Cancelled.",
        "chain_type": "Chain type:",
        "chain_other": "Other",
        "chain_select": "Select (1-4, default 4): ",
        "paste_key": "Paste private key (hidden): ",
        "empty_key": "❌ Private key cannot be empty.",
        "sui_warn": "⚠️  Sui private key is usually 32 or 64 bytes, got {n} bytes",
        "evm_warn": "⚠️  EVM private key is usually 32 bytes, got {n} bytes",
        "continue_yn": "Continue? (y/n): ",
        "derived_addr": "📍 Derived address: {addr}",
        "store_fail": "❌ Storage failed: {err}",
        "store_ok": "✅ Wallet [{alias}] saved to Keychain (password required for access)!",
        "remove_confirm": "⚠️  Confirm delete wallet '{alias}'? (yes/no): ",
        "remove_not_found": "❌ Wallet '{alias}' not found.",
        "remove_ok": "✅ Wallet [{alias}] deleted.",
        "remove_fail": "❌ Delete failed: {err}",
        "test_title": "🔍 Testing wallet '{alias}' access...",
        "test_chain": "Chain: {chain}",
        "test_addr": "Address: {addr}",
        "test_ok": "✅ Keychain access OK! Length: {n}",
        "test_fail": "❌ Cannot access Keychain",
        "test_err": "❌ Error: {err}",
        "acl_title": "🔒 Reset Keychain ACL for '{alias}'",
        "acl_desc": "   This removes all trusted apps (e.g. Python) and restores per-access prompts.",
        "acl_read_fail": "❌ Cannot read private key. Please use Keychain Access manually.",
        "acl_fail": "❌ Reset failed: {err}",
        "acl_ok": "✅ ACL for '{alias}' has been reset. Next access will prompt for authorization.",
        "export_empty": "📭 No wallets to export.",
        "usage_remove": "❌ Usage: wallet_panel.py remove <name>",
        "usage_test": "❌ Usage: wallet_panel.py test <name>",
        "usage_acl": "❌ Usage: wallet_panel.py reset-acl <name>",
        "rename_select_prompt": "🔄 Rename Wallet",
        "rename_input_hint": "  Enter 00 to cancel at any time",
        "rename_old_alias": "Current wallet alias",
        "rename_new_alias": "New wallet nickname",
        "rename_confirm": "Confirm rename '{old}' to '{new}'",
        "rename_success": "✅ Wallet renamed from '{old}' to '{new}'",
        "wallet_not_found": "❌ Wallet '{alias}' not found",
        "alias_already_exists": "❌ Alias '{alias}' already exists",
        "operation_cancelled": "Operation cancelled",
    },
}


def detect_lang() -> str:
    """Detect user language. Checks saved preference first, then env/locale."""
    # Check saved preference
    lang_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lang")
    try:
        if os.path.exists(lang_file):
            with open(lang_file) as f:
                saved = f.read().strip()
            if saved in ("zh", "en"):
                return saved
    except Exception:
        pass
    # Fallback to env/locale
    for env_var in ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        val = os.environ.get(env_var, "")
        if val.lower().startswith("zh"):
            return "zh"
    try:
        loc = locale.getlocale()[0] or ""
        if loc.lower().startswith("zh"):
            return "zh"
    except Exception:
        pass
    return "en"


LANG = detect_lang()


def t(key: str, **kwargs) -> str:
    """Get translated string."""
    s = STRINGS.get(LANG, STRINGS["en"]).get(key, STRINGS["en"].get(key, key))
    if kwargs:
        return s.format(**kwargs)
    return s


CHAIN_TYPES = {
    "1": {"name": "Sui", "id": "sui"},
    "2": {"name": "Solana", "id": "solana"},
    "3": {"name": "EVM", "id": "evm"},
    "4": {"name_zh": "其他", "name_en": "Other", "name": "Other", "id": "other"},
}


def get_chain_name(key: str) -> str:
    ct = CHAIN_TYPES.get(key, CHAIN_TYPES["4"])
    if ct["id"] == "other":
        return t("chain_other")
    return ct["name"]


# ── Registry ─────────────────────────────────────────

def get_registry() -> list:
    data = keyring.get_password(SERVICE_ID, REGISTRY_KEY)
    if not data:
        return []
    try:
        parsed = json.loads(data)
        if parsed and isinstance(parsed[0], str):
            return [{"alias": a, "chain": "unknown", "address": ""} for a in parsed]
        return parsed
    except json.JSONDecodeError:
        return []


def save_registry(wallets: list):
    keyring.set_password(SERVICE_ID, REGISTRY_KEY, json.dumps(wallets))


def find_wallet(wallets, alias):
    for w in wallets:
        if w["alias"] == alias:
            return w
    return None


def cmd_rename():
    """修改钱包昵称"""
    wallets = get_registry()
    if not wallets:
        print(t("no_wallets"))
        print(t("no_wallets_hint"))
        return
    
    # 显示当前钱包列表
    print(f"\n{t('wallet_list', count=len(wallets))}")
    print("=" * 50)
    for i, w in enumerate(wallets, 1):
        alias = w["alias"]
        chain = w.get("chain", "?")
        address = w.get("address", "")
        addr_display = address if address else t("no_address")
        print(f"  {i}. [{chain.upper()}] {alias}")
        print(f"     {t('address')}: {addr_display}")
    
    # 选择要修改的钱包
    print(f"\n{t('rename_select_prompt')}")
    print(f"  {t('rename_input_hint')}")
    
    old_alias = input(f"{t('rename_old_alias')}: ").strip()
    if old_alias == "00":
        print(t("operation_cancelled"))
        return
    
    wallet = find_wallet(wallets, old_alias)
    if not wallet:
        print(t("wallet_not_found", alias=old_alias))
        return
    
    # 输入新昵称
    new_alias = input(f"{t('rename_new_alias')}: ").strip()
    if new_alias == "00":
        print(t("operation_cancelled"))
        return
    
    # 检查新昵称是否已存在
    if find_wallet(wallets, new_alias):
        print(t("alias_already_exists", alias=new_alias))
        return
    
    # 确认修改
    confirm = input(f"{t('rename_confirm', old=old_alias, new=new_alias)} (y/N): ").strip().lower()
    if confirm != "y":
        print(t("operation_cancelled"))
        return
    
    # 更新昵称
    wallet["alias"] = new_alias
    save_registry(wallets)
    print(t("rename_success", old=old_alias, new=new_alias))


# ── Address Derivation ───────────────────────────────

def derive_sui_address(secret: str) -> str:
    try:
        import bech32
        from nacl.signing import SigningKey

        if secret.startswith("suiprivkey1"):
            hrp, data5bit = bech32.bech32_decode(secret)
            data8bit = bytes(bech32.convertbits(data5bit, 5, 8, False))
            scheme = data8bit[0]
            seed = data8bit[1:33]
        else:
            clean = secret.replace("0x", "")
            seed = bytes.fromhex(clean[:64])
            scheme = 0
        sk = SigningKey(seed)
        pk = sk.verify_key.encode()
        hasher = hashlib.blake2b(digest_size=32)
        hasher.update(bytes([scheme]) + pk)
        return "0x" + hasher.hexdigest()
    except Exception as e:
        return f"(derive failed: {e})"


def derive_evm_address(secret: str) -> str:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
        clean = secret.replace("0x", "")
        private_key = ec.derive_private_key(int(clean, 16), ec.SECP256K1(), default_backend())
        pub = private_key.public_key()
        pub_bytes = pub.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        try:
            from Crypto.Hash import keccak
            k = keccak.new(digest_bits=256)
            k.update(pub_bytes[1:])
            return "0x" + k.hexdigest()[-40:]
        except ImportError:
            return "(need pycryptodome for EVM address)"
    except Exception as e:
        return f"(derive failed: {e})"


def derive_address(chain: str, secret: str) -> str:
    if chain == "sui":
        return derive_sui_address(secret)
    elif chain == "evm":
        return derive_evm_address(secret)
    return ""


# ── Commands ─────────────────────────────────────────

def cmd_list():
    wallets = get_registry()
    if not wallets:
        print(t("no_wallets"))
        print(t("no_wallets_hint"))
        return

    print(f"\n{t('wallet_list', count=len(wallets))}")
    print("=" * 50)
    for i, w in enumerate(wallets, 1):
        alias = w["alias"]
        chain = w.get("chain", "?")
        address = w.get("address", "")
        addr_display = address if address else t("no_address")
        print(f"  {i}. [{chain.upper()}] {alias}")
        print(f"     {t('address')}: {addr_display}")
    print()


def cmd_add():
    print(f"\n{t('add_title')}")
    print("=" * 40)
    print("输入 '00' 可随时取消并返回")
    print()

    alias = input(f"{t('alias_prompt')} (输入 00 取消): ").strip()
    if alias == "00":
        print(t("cancelled"))
        return
    if not alias or alias == REGISTRY_KEY:
        print(t("invalid_alias"))
        return

    wallets = get_registry()
    existing = find_wallet(wallets, alias)
    if existing:
        overwrite = input(f"{t('exists_overwrite', alias=alias)} (输入 00 取消): ").lower()
        if overwrite == "00":
            print(t("cancelled"))
            return
        if overwrite != 'y':
            print(t("cancelled"))
            return

    print(f"\n{t('chain_type')}")
    for k in ["1", "2", "3", "4"]:
        print(f"  {k}. {get_chain_name(k)}")
    print("  00. 取消")
    chain_choice = input(f"{t('chain_select')} (输入 00 取消): ").strip() or "4"
    if chain_choice == "00":
        print(t("cancelled"))
        return
    chain_id = CHAIN_TYPES.get(chain_choice, CHAIN_TYPES["4"])["id"]

    secret = getpass.getpass(f"\n{t('paste_key')} (输入 00 取消): ")
    if secret == "00":
        print(t("cancelled"))
        return
    if not secret:
        print(t("empty_key"))
        return

    if chain_id == "sui":
        if not secret.startswith("suiprivkey1"):
            clean = secret.replace("0x", "")
            if len(clean) not in [64, 128]:
                print(t("sui_warn", n=len(clean) // 2))
                continue_choice = input(f"{t('continue_yn')} (输入 00 取消): ").lower()
                if continue_choice == "00":
                    print(t("cancelled"))
                    return
                if continue_choice != 'y':
                    return
    elif chain_id == "evm":
        clean = secret.replace("0x", "")
        if len(clean) != 64:
            print(t("evm_warn", n=len(clean) // 2))
            continue_choice = input(f"{t('continue_yn')} (输入 00 取消): ").lower()
            if continue_choice == "00":
                print(t("cancelled"))
                return
            if continue_choice != 'y':
                return

    address = derive_address(chain_id, secret)
    if address:
        print(f"\n{t('derived_addr', addr=address)}")

    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE_ID, "-a", alias],
            capture_output=True
        )
        result = subprocess.run(
            ["security", "add-generic-password", "-s", SERVICE_ID, "-a", alias, "-w", secret, "-T", ""],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(t("store_fail", err=result.stderr))
            return

        if existing:
            existing["chain"] = chain_id
            existing["address"] = address
        else:
            wallets.append({"alias": alias, "chain": chain_id, "address": address})
        save_registry(wallets)
        print(f"\n{t('store_ok', alias=alias)}")
    except Exception as e:
        print(t("store_fail", err=str(e)))


def cmd_add_noninteractive(alias: str, chain: str, private_key: str, skip_confirm: bool = False):
    """非交互式添加钱包"""
    print(f"\n🔐 非交互式添加钱包: {alias}")
    print("=" * 40)
    
    if not alias or alias == REGISTRY_KEY:
        print("❌ 无效的别名。")
        return False
    
    # 标准化链类型
    chain_lower = chain.lower()
    chain_id = None
    if chain_lower in ["sui", "1"]:
        chain_id = "sui"
    elif chain_lower in ["solana", "sol", "2"]:
        chain_id = "solana"
    elif chain_lower in ["evm", "eth", "ethereum", "3"]:
        chain_id = "evm"
    else:
        chain_id = "other"
    
    secret = private_key.strip()
    if not secret:
        print("❌ 私钥不能为空。")
        return False
    
    wallets = get_registry()
    existing = find_wallet(wallets, alias)
    
    if existing and not skip_confirm:
        print(f"⚠️  '{alias}' 已存在，需要覆盖。")
        # 在非交互模式下，如果存在且没有--yes，则失败
        print("❌ 钱包已存在，使用 --yes 覆盖或选择其他别名。")
        return False
    
    # 验证私钥格式（可选）
    if chain_id == "sui":
        if not secret.startswith("suiprivkey1"):
            clean = secret.replace("0x", "")
            if len(clean) not in [64, 128]:
                print(f"⚠️  Sui 私钥通常为 32 或 64 字节，当前 {len(clean)//2} 字节")
                if not skip_confirm:
                    print("❌ 私钥格式可能不正确。")
                    return False
    
    elif chain_id == "evm":
        clean = secret.replace("0x", "")
        if len(clean) != 64:
            print(f"⚠️  EVM 私钥通常为 32 字节，当前 {len(clean)//2} 字节")
            if not skip_confirm:
                print("❌ 私钥格式可能不正确。")
                return False
    
    # 推导地址
    address = derive_address(chain_id, secret)
    if address:
        print(f"📍 推导地址: {address}")
    
    try:
        # 删除现有条目（如果存在）
        subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE_ID, "-a", alias],
            capture_output=True
        )
        
        # 添加到 Keychain
        result = subprocess.run(
            ["security", "add-generic-password", "-s", SERVICE_ID, "-a", alias, "-w", secret, "-T", ""],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            print(f"❌ 存储失败: {result.stderr}")
            return False
        
        # 更新注册表
        if existing:
            existing["chain"] = chain_id
            existing["address"] = address
        else:
            wallets.append({"alias": alias, "chain": chain_id, "address": address})
        
        save_registry(wallets)
        print(f"\n✅ 钱包 '{alias}' 添加成功！")
        print(f"   链类型: {chain_id}")
        print(f"   地址: {address or '未知'}")
        return True
        
    except Exception as e:
        print(f"❌ 存储失败: {str(e)}")
        return False


def cmd_remove(alias: str):
    wallets = get_registry()
    existing = find_wallet(wallets, alias)
    if not existing:
        print(t("remove_not_found", alias=alias))
        return

    confirm = input(f"{t('remove_confirm', alias=alias)} (输入 00 取消): ")
    if confirm == "00":
        print(t("cancelled"))
        return
    if confirm != 'yes':
        print(t("cancelled"))
        return

    try:
        keyring.delete_password(SERVICE_ID, alias)
        wallets.remove(existing)
        save_registry(wallets)
        print(t("remove_ok", alias=alias))
    except Exception as e:
        print(t("remove_fail", err=str(e)))


def cmd_test(alias: str):
    print(f"\n{t('test_title', alias=alias)}")
    wallets = get_registry()
    w = find_wallet(wallets, alias)
    if w:
        print(t("test_chain", chain=w.get("chain", "?").upper()))
        print(t("test_addr", addr=w.get("address", "N/A")))
    try:
        pk = keyring.get_password(SERVICE_ID, alias)
        if pk:
            print(t("test_ok", n=len(pk)))
        else:
            print(t("test_fail"))
    except Exception as e:
        print(t("test_err", err=str(e)))


def cmd_reset_acl(alias: str):
    wallets = get_registry()
    w = find_wallet(wallets, alias)
    if not w:
        print(t("remove_not_found", alias=alias))
        return

    print(f"\n{t('acl_title', alias=alias)}")
    print(t("acl_desc"))

    pk = keyring.get_password(SERVICE_ID, alias)
    if not pk:
        print(t("acl_read_fail"))
        return

    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", SERVICE_ID, "-a", alias],
            capture_output=True
        )
        result = subprocess.run(
            ["security", "add-generic-password", "-s", SERVICE_ID, "-a", alias, "-w", pk, "-T", ""],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(t("acl_fail", err=result.stderr))
            return
        print(t("acl_ok", alias=alias))
    except Exception as e:
        print(t("acl_fail", err=str(e)))
    finally:
        pk = None
        del pk


def cmd_export_config():
    wallets = get_registry()
    if not wallets:
        print(t("export_empty"))
        return
    print("\n# OpenClaw Wallet Config (config.yaml snippet)")
    print("wallet:")
    print(f"  service_id: {SERVICE_ID}")
    print(f"  default: {wallets[0]['alias']}")
    print(f"  accounts:")
    for w in wallets:
        print(f"    - alias: {w['alias']}")
        print(f"      chain: {w.get('chain', '?')}")
        print(f"      address: {w.get('address', '')}")


def main():
    parser = argparse.ArgumentParser(description=t("panel_title"))
    parser.add_argument('command', choices=['list', 'add', 'remove', 'test', 'reset-acl', 'export-config', 'rename', 'transfer'])
    parser.add_argument('name', nargs='?', help='Wallet alias')
    
    # 添加钱包的额外参数
    parser.add_argument('--chain', help='Chain type (Sui, Solana, EVM, Other)')
    parser.add_argument('--private-key', help='Private key (use with caution)')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompts')
    
    # 转账的额外参数
    parser.add_argument('--to', help='Recipient address for transfer')
    parser.add_argument('--amount', help='Amount to transfer')
    parser.add_argument('--token', help='Token type (SUI, SOL, ETH, etc)')
    parser.add_argument('--memo', help='Memo for transfer')
    
    args = parser.parse_args()

    if args.command == 'list':
        cmd_list()
    elif args.command == 'add':
        if args.name and args.chain and args.private_key:
            # 非交互式添加
            cmd_add_noninteractive(args.name, args.chain, args.private_key, args.yes)
        else:
            # 交互式添加
            cmd_add()
    elif args.command == 'remove':
        if not args.name:
            print(t("usage_remove"))
            return
        cmd_remove(args.name)
    elif args.command == 'test':
        if not args.name:
            print(t("usage_test"))
            return
        cmd_test(args.name)
    elif args.command == 'reset-acl':
        if not args.name:
            print(t("usage_acl"))
            return
        cmd_reset_acl(args.name)
    elif args.command == 'export-config':
        cmd_export_config()
    elif args.command == 'rename':
        cmd_rename()
    elif args.command == 'transfer':
        if not args.name or not args.to or not args.amount:
            print("用法: python3 wallet_panel.py transfer <钱包别名> --to <地址> --amount <金额> [--token <代币>] [--memo <备注>]")
            return
        cmd_transfer(args.name, args.to, args.amount, args.token, args.memo)


def cmd_transfer(alias: str, to_address: str, amount: str, token: str = None, memo: str = None):
    """执行转账"""
    print(f"\n💸 从钱包 '{alias}' 转账")
    print("=" * 40)
    
    # 获取钱包信息
    wallets = get_registry()
    wallet = find_wallet(wallets, alias)
    if not wallet:
        print(f"❌ 钱包 '{alias}' 不存在。")
        return False
    
    chain_id = wallet.get("chain", "unknown")
    print(f"链类型: {chain_id}")
    print(f"收款地址: {to_address}")
    print(f"金额: {amount} {token or '代币'}")
    if memo:
        print(f"备注: {memo}")
    
    # 根据链类型调用相应的转账脚本
    try:
        if chain_id == "sui":
            # 调用 SUI 转账脚本
            import subprocess
            import os
            
            script_dir = os.path.dirname(os.path.abspath(__file__))
            cmd = ["python3", "sui_transfer.py", alias, to_address, amount]
            if memo:
                cmd.extend(["--memo", memo])
            
            print(f"\n🚀 执行 SUI 转账...")
            result = subprocess.run(cmd, cwd=script_dir, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"✅ 转账成功！")
                print(result.stdout)
                return True
            else:
                print(f"❌ 转账失败:")
                print(result.stderr if result.stderr else result.stdout)
                return False
                
        elif chain_id == "solana":
            # 调用 Solana 转账脚本
            import subprocess
            import os
            
            script_dir = os.path.dirname(os.path.abspath(__file__))
            cmd = ["python3", "solana_transfer.py", alias, to_address, amount]
            if token and token != "SOL":
                cmd.extend(["--token", token])
            if memo:
                cmd.extend(["--memo", memo])
            
            print(f"\n🚀 执行 Solana 转账...")
            result = subprocess.run(cmd, cwd=script_dir, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"✅ 转账成功！")
                print(result.stdout)
                return True
            else:
                print(f"❌ 转账失败:")
                print(result.stderr if result.stderr else result.stdout)
                return False
                
        elif chain_id == "evm":
            # 调用 EVM 转账脚本
            import subprocess
            import os
            
            script_dir = os.path.dirname(os.path.abspath(__file__))
            cmd = ["python3", "evm_transfer.py", alias, to_address, amount]
            if token and token != "ETH":
                cmd.extend(["--token", token])
            if memo:
                cmd.extend(["--memo", memo])
            
            print(f"\n🚀 执行 EVM 转账...")
            result = subprocess.run(cmd, cwd=script_dir, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print(f"✅ 转账成功！")
                print(result.stdout)
                return True
            else:
                print(f"❌ 转账失败:")
                print(result.stderr if result.stderr else result.stdout)
                return False
                
        else:
            print(f"❌ 不支持的链类型: {chain_id}")
            return False
            
    except Exception as e:
        print(f"❌ 转账时出错: {str(e)}")
        return False


if __name__ == "__main__":
    main()

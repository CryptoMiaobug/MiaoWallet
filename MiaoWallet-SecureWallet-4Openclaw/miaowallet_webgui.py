#!/usr/bin/env python3
"""
MiaoWallet Pro - Web GUI v2 (树状图版)
内置 http.server + 浏览器，零外部依赖
"""

import http.server
import json
import os
import sys
import threading
import webbrowser
import socket
import re
import hashlib
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from mnemonic_manager_bip44 import MnemonicManagerBIP44 as MnemonicManager
    MNEMONIC_MANAGER_AVAILABLE = True
    BIP44_MODE = True
    print("✅ 使用BIP44标准模式")
except ImportError as e:
    print(f"❌ 无法导入BIP44助记词管理器: {e}")
    MNEMONIC_MANAGER_AVAILABLE = False
    BIP44_MODE = False

if '__file__' in globals():
    WALLET_DIR = os.path.dirname(os.path.abspath(__file__))
else:
    WALLET_DIR = os.getcwd()
WALLET_FILE = os.path.join(WALLET_DIR, ".wallet_addresses.json")

manager = MnemonicManager() if MNEMONIC_MANAGER_AVAILABLE else None

# Sui RPC & token metadata
SUI_RPC = "https://fullnode.mainnet.sui.io:443"
TOKEN_META = {
    "0x2::sui::SUI": {"symbol": "SUI", "decimals": 9, "icon": "💧"},
    "0x5d4b302506645c37ff133b98c4b50a5ae14841659738d6d733d59d0d217a93bf::coin::COIN": {"symbol": "USDC", "decimals": 6, "icon": "💵"},
    "0x9258181f5ceac8dbffb7030890243caed69a9599d2886d957a9cb7656af3bdb3::wal::WAL": {"symbol": "WAL", "decimals": 9, "icon": "🐋"},
    "0x06864a6f921804860930db6ddbe2e16acdf8504495ea7481637a1c8b9a8fe54b::cetus::CETUS": {"symbol": "CETUS", "decimals": 9, "icon": "🐬"},
}

def fetch_sui_balances(address):
    """Query all token balances for a Sui address via RPC"""
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "suix_getAllBalances",
            "params": [address]
        }).encode()
        req = urllib.request.Request(SUI_RPC, data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        balances = []
        for b in data.get("result", []):
            coin_type = b.get("coinType", "")
            total_raw = int(b.get("totalBalance", "0"))
            meta = TOKEN_META.get(coin_type, {})
            symbol = meta.get("symbol", coin_type.split("::")[-1] if "::" in coin_type else "???")
            decimals = meta.get("decimals", 9)
            icon = meta.get("icon", "🪙")
            amount = total_raw / (10 ** decimals)
            if amount > 0 or coin_type == "0x2::sui::SUI":
                balances.append({"symbol": symbol, "amount": round(amount, 6), "icon": icon, "coinType": coin_type})
        # Ensure SUI is always first
        balances.sort(key=lambda x: (0 if x["symbol"] == "SUI" else 1, x["symbol"]))
        return balances
    except Exception as e:
        print(f"[Balance] Error fetching {address}: {e}")
        return []


def load_wallets_raw():
    """加载原始扁平数据"""
    if os.path.exists(WALLET_FILE):
        with open(WALLET_FILE, 'r') as f:
            return json.load(f)
    return {}


def get_mnemonic_from_keychain(wallet_name):
    """从Keychain获取助记词"""
    try:
        import keyring
        service_name = "openclaw_bot"
        mnemonic = keyring.get_password(service_name, f"mnemonic_{wallet_name}")
        return mnemonic
    except Exception as e:
        print(f"从Keychain获取助记词失败: {e}")
        return None


def save_mnemonic_with_nickname(mnemonic, nickname, wallet_name):
    """保存助记词和昵称到Keychain"""
    try:
        import keyring
        service_name = "openclaw_bot"
        
        # 保存助记词
        keyring.set_password(service_name, f"mnemonic_{wallet_name}", mnemonic)
        
        # 保存助记词昵称
        keyring.set_password(service_name, f"nickname_{wallet_name}", nickname)
        
        return True
    except Exception as e:
        print(f"保存助记词和昵称失败: {e}")
        return False


def get_mnemonic_nickname_from_keychain(wallet_name):
    """从Keychain获取助记词昵称"""
    try:
        import keyring
        service_name = "openclaw_bot"
        nickname = keyring.get_password(service_name, f"nickname_{wallet_name}")
        return nickname
    except Exception as e:
        print(f"从Keychain获取助记词昵称失败: {e}")
        return None


def get_mnemonic_by_hash(mnemonic_hash):
    """
    根据助记词哈希找到对应的助记词
    返回: 助记词字符串 或 None
    """
    try:
        import keyring
        service_name = "openclaw_bot"
        
        # 从所有钱包中查找匹配的助记词
        raw = load_wallets_raw()
        wallet_names = set()
        chain_suffixes = ["_sui", "_solana", "_ethereum"]
        
        for key in raw:
            wallet_name = key
            for suffix in chain_suffixes:
                if key.endswith(suffix):
                    wallet_name = key[: -len(suffix)]
                    break
            wallet_names.add(wallet_name)
        
        for wallet_name in wallet_names:
            # 获取助记词
            mnemonic = keyring.get_password(service_name, f"mnemonic_{wallet_name}")
            if mnemonic:
                # 计算哈希
                m_hash = hashlib.sha256(mnemonic.encode()).hexdigest()[:16]
                if m_hash == mnemonic_hash:
                    return mnemonic
        
        return None
    except Exception as e:
        print(f"根据哈希查找助记词失败: {e}")
        return None


def load_wallets_tree():
    """
    构建三层树状结构:
    {
      "mnemonic_hash1": {
        "mnemonic_preview": "abandon abandon abandon...",
        "wallets": {
          "wallet_name1": {
            "SUI": "0x...",
            "Solana": "abc...",
            "Ethereum": "0x..."
          }
        }
      }
    }
    
    支持真正的助记词分组
    """
    raw = load_wallets_raw()
    tree = {}
    chain_suffixes = ["_sui", "_solana", "_ethereum"]
    # 兼容旧的_evm后缀
    old_evm_suffix = "_evm"
    
    # 收集所有钱包名称
    wallet_names = set()
    for key in raw:
        wallet_name = key
        for suffix in chain_suffixes:
            if key.endswith(suffix):
                wallet_name = key[: -len(suffix)]
                break
        # 检查旧的_evm后缀
        if key.endswith(old_evm_suffix):
            wallet_name = key[: -len(old_evm_suffix)]
        wallet_names.add(wallet_name)
    
    # 按助记词分组
    mnemonic_to_wallets = {}
    
    for wallet_name in sorted(wallet_names):
        # 尝试获取该钱包的助记词昵称
        nickname = get_mnemonic_nickname_from_keychain(wallet_name)
        
        if nickname:
            # 如果有昵称，使用昵称
            mnemonic_preview = f"🔐 {nickname}"
            
            # 获取助记词用于分组
            mnemonic = get_mnemonic_from_keychain(wallet_name)
            if mnemonic:
                # 使用助记词哈希作为分组ID
                mnemonic_hash = hashlib.sha256(mnemonic.encode()).hexdigest()[:16]
            else:
                # 如果没有助记词，使用昵称哈希
                mnemonic_hash = hashlib.sha256(nickname.encode()).hexdigest()[:16]
        else:
            # 如果没有昵称，尝试获取助记词
            mnemonic = get_mnemonic_from_keychain(wallet_name)
            
            if mnemonic:
                # 使用助记词哈希作为分组ID
                mnemonic_hash = hashlib.sha256(mnemonic.encode()).hexdigest()[:16]
                
                # 使用助记词前4个单词作为预览
                words = mnemonic.split()
                if len(words) >= 4:
                    mnemonic_preview = f"🔐 {' '.join(words[:4])}..."
                else:
                    mnemonic_preview = f"🔐 {mnemonic[:20]}..."
            else:
                # 如果既没有昵称也没有助记词，使用钱包名作为分组
                mnemonic_hash = f"wallet_{wallet_name}"
                mnemonic_preview = f"🔑 钱包: {wallet_name}"
        
        # 添加到分组
        if mnemonic_hash not in mnemonic_to_wallets:
            mnemonic_to_wallets[mnemonic_hash] = {
                "preview": mnemonic_preview,
                "wallets": []
            }
        
        mnemonic_to_wallets[mnemonic_hash]["wallets"].append(wallet_name)
    
    # 构建树状结构
    for mnemonic_hash, group_info in mnemonic_to_wallets.items():
        # 检查分组中是否有钱包有昵称
        group_nickname = None
        for wallet_name in group_info["wallets"]:
            nickname = get_mnemonic_nickname_from_keychain(wallet_name)
            if nickname:
                group_nickname = nickname
                break
        
        # 如果有昵称，使用昵称作为分组预览
        if group_nickname:
            mnemonic_preview = f"🔐 {group_nickname}"
        else:
            mnemonic_preview = group_info["preview"]
        
        tree[mnemonic_hash] = {
            "mnemonic_preview": mnemonic_preview,
            "wallets": {}
        }
        
        for wallet_name in group_info["wallets"]:
            tree[mnemonic_hash]["wallets"][wallet_name] = {}
            
            # 收集该钱包的所有链地址
            for suffix in chain_suffixes:
                key = f"{wallet_name}{suffix}"
                if key in raw:
                    chain = suffix[1:].upper()
                    if chain == "SOLANA":
                        chain = "Solana"
                    elif chain == "ETHEREUM":
                        chain = "Ethereum"
                    tree[mnemonic_hash]["wallets"][wallet_name][chain] = raw[key]
            
            # 处理旧的_evm后缀
            old_key = f"{wallet_name}_evm"
            if old_key in raw:
                tree[mnemonic_hash]["wallets"][wallet_name]["Ethereum"] = raw[old_key]
    
    # 如果没有找到任何分组，让每个钱包独立显示
    if not tree:
        for wallet_name in sorted(wallet_names):
            # 每个钱包作为独立的助记词分组
            mnemonic_hash = f"wallet_{wallet_name}"
            tree[mnemonic_hash] = {
                "mnemonic_preview": f"🔑 钱包: {wallet_name}",
                "wallets": {
                    wallet_name: {}
                }
            }
            
            # 收集该钱包的所有链地址
            for suffix in chain_suffixes:
                key = f"{wallet_name}{suffix}"
                if key in raw:
                    chain = suffix[1:].upper()
                    if chain == "SOLANA":
                        chain = "Solana"
                    elif chain == "ETHEREUM":
                        chain = "Ethereum"
                    tree[mnemonic_hash]["wallets"][wallet_name][chain] = raw[key]
            
            # 处理旧的_evm后缀
            old_key = f"{wallet_name}_evm"
            if old_key in raw:
                tree[mnemonic_hash]["wallets"][wallet_name]["Ethereum"] = raw[old_key]
    
    return tree


def delete_wallet(name):
    """删除一个钱包的所有链地址 + Keychain"""
    if manager:
        manager.delete_wallet(name)
        return True
    # fallback: 手动删文件
    raw = load_wallets_raw()
    keys = [k for k in raw if k == name or k.startswith(f"{name}_")]
    for k in keys:
        del raw[k]
    with open(WALLET_FILE, "w") as f:
        json.dump(raw, f, indent=2)
    return True


def rename_wallet(old_name, new_name):
    """重命名钱包"""
    raw = load_wallets_raw()
    chain_suffixes = ["_sui", "_solana", "_ethereum"]
    
    # 检查名称有效性
    if not new_name or not new_name.strip():
        raise ValueError("钱包名称不能为空")
    
    new_name = new_name.strip()
    
    # 检查新名称是否已存在
    for suffix in chain_suffixes:
        if f"{new_name}{suffix}" in raw:
            raise ValueError(f"钱包名称 '{new_name}' 已存在")
    
    # 重命名所有链地址
    for suffix in chain_suffixes:
        old_key = f"{old_name}{suffix}"
        if old_key in raw:
            new_key = f"{new_name}{suffix}"
            raw[new_key] = raw[old_key]
            del raw[old_key]
    
    # 保存更新后的数据
    with open(WALLET_FILE, "w") as f:
        json.dump(raw, f, indent=2)
    
    # 重命名Keychain中的助记词和昵称
    try:
        import keyring
        service_name = "openclaw_bot"
        
        # 重命名助记词
        mnemonic = keyring.get_password(service_name, f"mnemonic_{old_name}")
        if mnemonic:
            keyring.set_password(service_name, f"mnemonic_{new_name}", mnemonic)
            keyring.delete_password(service_name, f"mnemonic_{old_name}")
        
        # 重命名助记词昵称
        nickname = keyring.get_password(service_name, f"nickname_{old_name}")
        if nickname:
            keyring.set_password(service_name, f"nickname_{new_name}", nickname)
            keyring.delete_password(service_name, f"nickname_{old_name}")
            
    except Exception as e:
        print(f"Keychain重命名失败: {e}")
        # Keychain失败不影响文件重命名
    
    return True


def rename_mnemonic(mnemonic_hash, new_name):
    """修改助记词昵称"""
    if not new_name or not new_name.strip():
        raise ValueError("助记词昵称不能为空")
    
    new_name = new_name.strip()
    
    # 获取助记词分组下的所有钱包
    tree = load_wallets_tree()
    if mnemonic_hash not in tree:
        raise ValueError(f"未找到助记词分组: {mnemonic_hash}")
    
    # 更新助记词昵称
    tree[mnemonic_hash]["mnemonic_preview"] = new_name
    
    # 更新Keychain中的助记词昵称
    try:
        import keyring
        service_name = "openclaw_bot"
        
        # 获取该助记词分组下的所有钱包
        wallet_names = list(tree[mnemonic_hash]["wallets"].keys())
        
        # 更新每个钱包的助记词昵称
        for wallet_name in wallet_names:
            # 获取助记词
            mnemonic = keyring.get_password(service_name, f"mnemonic_{wallet_name}")
            if mnemonic:
                # 更新助记词昵称
                keyring.set_password(service_name, f"nickname_{wallet_name}", new_name)
    
    except Exception as e:
        print(f"Keychain更新助记词昵称失败: {e}")
        # Keychain失败不影响界面显示
    
    # 注意：助记词昵称只存储在Keychain中，不存储在.wallet_addresses.json文件中
    # 界面显示时从Keychain读取，所以这里不需要保存到文件
    
    return True


def delete_mnemonic(mnemonic_hash):
    """删除一个助记词及其所有钱包"""
    raw = load_wallets_raw()
    chain_suffixes = ["_sui", "_solana", "_ethereum", "_evm"]
    
    # 收集所有钱包名
    wallet_names = set()
    for key in raw:
        wn = key
        for suffix in chain_suffixes:
            if key.endswith(suffix):
                wn = key[:-len(suffix)]
                break
        wallet_names.add(wn)
    
    # 找出属于该助记词哈希的钱包
    wallets_to_delete = []
    try:
        import keyring
        service_name = "openclaw_bot"
        for wn in wallet_names:
            mnemonic = keyring.get_password(service_name, f"mnemonic_{wn}")
            if mnemonic:
                m_hash = hashlib.sha256(mnemonic.encode()).hexdigest()[:16]
                if m_hash == mnemonic_hash:
                    wallets_to_delete.append(wn)
    except Exception as e:
        print(f"Keychain查询失败: {e}")
    
    # 如果 Keychain 没匹配到，尝试从 tree 匹配（兜底）
    if not wallets_to_delete:
        try:
            tree = load_wallets_tree()
            if mnemonic_hash in tree:
                wallets_to_delete = list(tree[mnemonic_hash]["wallets"].keys())
        except Exception:
            pass
    
    if not wallets_to_delete:
        return False
    
    # 删除钱包地址
    for wallet_name in wallets_to_delete:
        for suffix in chain_suffixes:
            key = f"{wallet_name}{suffix}"
            if key in raw:
                del raw[key]
        
        # 删除 Keychain 数据
        try:
            import keyring
            service_name = "openclaw_bot"
            try:
                keyring.delete_password(service_name, f"mnemonic_{wallet_name}")
            except Exception:
                pass
            try:
                keyring.delete_password(service_name, f"nickname_{wallet_name}")
            except Exception:
                pass
        except Exception as e:
            print(f"删除Keychain数据失败: {e}")
    
    # 保存更新后的数据
    with open(WALLET_FILE, "w") as f:
        json.dump(raw, f, indent=2)
    
    return True


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MiaoWallet Pro</title>
<style>
:root {
  --bg: #1a1a2e; --bg2: #16213e; --bg3: #0f3460; --bg4: #2d4059;
  --red: #e94560; --blue: #3498db; --green: #2ecc71; --purple: #9b59b6;
  --yellow: #f39c12; --text: #fff; --muted: #999;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg); color: var(--text); min-height: 100vh; }

.header { background: var(--bg2); padding: 18px; text-align: center; position:relative; }
.header h1 { font-size: 1.4em; }
.status-bar { background: var(--bg3); padding: 8px 20px; font-size: 0.85em; color: var(--red); }

.container { display: flex; gap: 20px; padding: 20px; max-width: 1100px; margin: 0 auto; }
.left { flex: 1; min-width: 0; }
.right { width: 260px; flex-shrink: 0; }

.panel { background: var(--bg2); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.panel h2 { font-size: 1.05em; margin-bottom: 12px; }

/* Buttons */
.btn { display:block; width:100%; padding:11px; margin-bottom:7px; border:none;
       border-radius:6px; color:#fff; font-size:0.95em; cursor:pointer; font-weight:600; }
.btn:hover { opacity:0.85; }
.btn-red { background:var(--red); } .btn-blue { background:var(--blue); }
.btn-green { background:var(--green); } .btn-purple { background:var(--purple); }
.btn-sm { display:inline-block; width:auto; padding:4px 10px; font-size:0.8em; margin:0; }
.btn-primary { background:#2980b9; }
.btn-warning { background:#f39c12; }
.btn-danger { background:#c0392b; }

/* Tree */
.tree-empty { color:var(--muted); padding:20px; text-align:center; }

.mnemonic-node { margin-bottom: 12px; }
.mnemonic-header {
  display: flex; align-items: center; gap: 8px;
  background: linear-gradient(90deg, var(--bg3), #1a3a5e);
  padding: 12px 16px; border-radius: 8px; cursor: pointer;
  user-select: none; transition: background 0.15s; border-left: 4px solid var(--red);
}
.mnemonic-header:hover { background: linear-gradient(90deg, #1a3a5e, #1a4a6e); }
.mnemonic-header .arrow { transition: transform 0.2s; font-size: 0.85em; color: var(--muted); }
.mnemonic-header.expanded .arrow { transform: rotate(90deg); }
.mnemonic-header .name { font-weight: 700; flex: 1; font-size: 0.95em; }
.mnemonic-header .count { font-size: 0.8em; color: var(--muted); background: rgba(0,0,0,0.3); padding: 2px 8px; border-radius: 10px; }

.mnemonic-children { display: none; margin-left: 20px; margin-top: 6px; }
.mnemonic-children.show { display: block; }

.wallet-node { margin-bottom: 8px; }
.wallet-header {
  display: flex; align-items: center; gap: 8px;
  background: var(--bg3); padding: 10px 14px; border-radius: 6px; cursor: pointer;
  user-select: none; transition: background 0.15s; border-left: 3px solid var(--blue);
}
.wallet-header:hover { background: #163d6e; }
.wallet-header .arrow { transition: transform 0.2s; font-size: 0.8em; color: var(--muted); }
.wallet-header.expanded .arrow { transform: rotate(90deg); }
.wallet-header .name { font-weight: 600; flex: 1; font-size: 0.9em; }
.wallet-header .count { font-size: 0.75em; color: var(--muted); }

.wallet-children { display: none; margin-left: 24px; margin-top: 4px; }
.wallet-children.show { display: block; }

.chain-row {
  display: flex; align-items: center; gap: 10px; padding: 7px 12px;
  background: var(--bg4); border-radius: 4px; margin-bottom: 3px; font-size: 0.85em;
}
.chain-tag { font-weight: 700; min-width: 60px; }
.chain-tag.sui { color: #4da2ff; }
.chain-tag.solana { color: #9945ff; }
.chain-tag.ethereum { color: #627eea; }
.chain-tag.unknown { color: var(--muted); }
.chain-addr { flex: 1; word-break: break-all; color: #ccc; font-family: 'Menlo','Monaco',monospace; font-size: 0.82em; }
.chain-copy { cursor:pointer; opacity:0.5; font-size:0.9em; }
.chain-copy:hover { opacity:1; }

/* Balance */
.balance-row { display:flex; flex-wrap:wrap; gap:8px; padding:6px 12px; background:rgba(77,162,255,0.06); border-radius:4px; margin-bottom:3px; }
.balance-tag { display:inline-flex; align-items:center; gap:4px; background:rgba(255,255,255,0.06); padding:3px 10px; border-radius:12px; font-size:0.82em; color:#ccc; }
.balance-tag .bal-amount { color:#4fc3f7; font-weight:600; font-family:'Menlo','Monaco',monospace; }
.balance-loading { color:var(--muted); font-size:0.8em; padding:4px 12px; }

/* Modal */
.overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:100;
           justify-content:center; align-items:center; }
.overlay.active { display:flex; }
.modal { background:var(--bg); border-radius:12px; width:92%; max-width:600px;
         max-height:88vh; overflow-y:auto; padding:24px; }
.modal h2 { color:var(--red); margin-bottom:16px; }
.field { margin-bottom:14px; }
.field label { display:block; margin-bottom:5px; color:#ccc; font-size:0.88em; }
.field textarea, .field input[type=text] {
  width:100%; padding:10px; background:var(--bg4); border:1px solid #3d5079; border-radius:6px;
  color:#fff; font-family:'Menlo','Monaco',monospace; font-size:0.92em; resize:vertical; }
.field textarea { height:85px; }
.field input[type=text] { height:38px; }
.modal-btns { display:flex; gap:10px; margin-top:18px; }
.modal-btns .btn { flex:1; }
.msg { padding:10px; border-radius:6px; margin-top:10px; font-size:0.88em; }
.msg-ok { background:#1a4a2e; color:var(--green); }
.msg-err { background:#4a1a2e; color:var(--red); }
.example-btn { background:var(--yellow); border:none; border-radius:4px; color:#fff;
               padding:5px 12px; cursor:pointer; font-size:0.8em; margin-top:4px; }
.result-box { background:var(--bg3); border-radius:8px; padding:14px; margin-top:14px; }
.result-box .addr-line { margin:5px 0; font-size:0.85em; }
.result-box .r-chain { color:var(--blue); font-weight:bold; }
.result-box .r-addr { color:#ccc; word-break:break-all; font-family:monospace; font-size:0.82em; }
.info { background:var(--bg3); border-radius:8px; padding:14px; font-size:0.82em; color:#aaa; line-height:1.6; }
.lang-btn { position:absolute; right:18px; top:50%; transform:translateY(-50%);
  background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.25); border-radius:4px;
  color:#fff; padding:3px 10px; font-size:0.78em; cursor:pointer; font-weight:600; }
.lang-btn:hover { background:rgba(255,255,255,0.22); }
</style>
</head>
<body>

<div class="header"><h1 id="header-title">🔐 MiaoWallet Pro</h1><button class="lang-btn" onclick="toggleLang()" id="lang-btn">中/EN</button></div>
<div class="status-bar" id="status">就绪</div>

<div class="container">
  <div class="left">
    <div class="panel">
      <h2 id="wallet-list-title">📋 钱包列表</h2>
      <div id="wallet-tree"><div class="tree-empty">加载中...</div></div>
    </div>
  </div>
  <div class="right">
    <div class="panel">
      <h2 id="func-title">🚀 功能</h2>
      <button class="btn btn-red" onclick="openAddModal()" id="btn-add">➕ 新助记词</button>
      <button class="btn btn-blue" onclick="refreshTree()" id="btn-refresh">🔄 刷新</button>
      <button class="btn" style="background:#2d6a4f" onclick="openWhitelistModal()" id="btn-whitelist">🛡 白名单管理</button>
      <button class="btn" style="background:#e85d04" onclick="window.open('https://cryptomiaobug.github.io/rps-sui-game/','_blank')" id="btn-rps">🎮 来玩剪刀石头布</button>
      <button class="btn" style="background:#8b5cf6" onclick="resetKeychainAuth()" id="btn-reset-keychain">🔓 重置 Keychain 授权</button>
      <button class="btn" style="background:#8b5cf6" onclick="window.open('https://crowdwalrus.xyz/campaigns/rps-sui','_blank')" id="btn-support">💜 支持我们</button>
    </div>

    <div class="info" id="info-box">
      <strong id="info-title">📖 使用说明</strong><br><br>
      <span id="info-content">
      1. 点击「新助记词」添加钱包<br>
      2. 输入 BIP39 助记词（12/24词）<br>
      3. 自动生成 SUI / Solana / Ethereum 地址<br>
      4. 助记词安全存储到 macOS Keychain<br><br>
      点击钱包名展开/折叠地址<br>
      点击 📋 复制地址
      </span>
    </div>
  </div>
</div>

<!-- Session Management Panel (full width) -->
<div style="max-width:1100px;margin:0 auto;padding:0 20px 20px">
  <div class="panel" id="session-panel" style="border:1px solid rgba(79,195,247,0.3);background:linear-gradient(135deg,#0d1520,#1a2540)">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
      <h2 style="margin:0">🔐 <span id="session-panel-title">签名授权 Session</span></h2>
      <div style="flex:1"></div>
      <label style="color:#aaa;font-size:0.9em;white-space:nowrap" id="session-wallet-label">钱包:</label>
      <select id="session-wallet" style="padding:8px 12px;background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:8px;font-size:0.9em;min-width:200px">
        <option value="">加载中...</option>
      </select>
    </div>

    <div style="display:flex;gap:20px">
      <!-- API Session -->
      <div style="flex:1;border:1px solid rgba(79,195,247,0.2);border-radius:10px;padding:20px;background:rgba(79,195,247,0.04)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
          <span style="font-size:1.3em">⚡</span>
          <span style="font-weight:700;color:#4fc3f7;font-size:1.1em">API Mode</span>
          <span id="api-badge" style="font-size:0.75em;padding:3px 10px;border-radius:10px;background:rgba(239,83,80,0.2);color:#ef5350;margin-left:auto">未授权</span>
        </div>
        <p style="font-size:0.82em;color:#888;margin-bottom:12px" id="api-desc">MCP Server · AI Agent 通过命令自动签名</p>
        <div id="api-inactive">
          <div style="display:flex;gap:12px;margin-bottom:12px">
            <div style="flex:1">
              <label style="color:#888;font-size:0.85em" id="api-time-label">⏱ 授权时间（分钟）</label>
              <input id="api-time" type="number" value="30" min="0" style="width:100%;padding:8px;margin-top:4px;background:#222;color:#fff;border:1px solid #444;border-radius:6px">
            </div>
            <div style="flex:1">
              <label style="color:#888;font-size:0.85em" id="api-signs-label">✍️ 签名次数上限</label>
              <input id="api-signs" type="number" value="10" min="0" style="width:100%;padding:8px;margin-top:4px;background:#222;color:#fff;border:1px solid #444;border-radius:6px">
            </div>
          </div>
          <button class="btn" style="background:#0e7490;padding:10px;font-size:1em" onclick="doStartSession('api')" id="btn-auth-api">⚡ 授权 API</button>
        </div>
        <div id="api-active" style="display:none">
          <div style="display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:0.9em;margin-bottom:12px">
            <span style="color:#888" id="api-addr-label2">📍 地址</span><span id="api-addr" style="color:#fff;font-family:monospace;font-size:0.85em;word-break:break-all">-</span>
            <span style="color:#888" id="api-signed-label">✍️ 已签名</span><span><span id="api-count" style="color:#4fc3f7;font-weight:700">0</span> <span id="api-limit" style="color:#666">/ ∞</span></span>
            <span style="color:#888" id="api-remaining-label">⏱ 剩余时间</span><span id="api-remaining" style="color:#fbbf24;font-weight:600">-</span>
          </div>
          <button class="btn btn-danger" style="padding:8px;background:#dc2626" onclick="doRevokeSession('api')" id="btn-revoke-api">🔒 撤销 API 授权</button>
        </div>
      </div>

      <!-- Browser Session -->
      <div style="flex:1;border:1px solid rgba(179,136,255,0.2);border-radius:10px;padding:20px;background:rgba(179,136,255,0.04)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
          <span style="font-size:1.3em">🌐</span>
          <span style="font-weight:700;color:#b388ff;font-size:1.1em">Browser Mode</span>
          <span id="browser-badge" style="font-size:0.75em;padding:3px 10px;border-radius:10px;background:rgba(239,83,80,0.2);color:#ef5350;margin-left:auto">未连接</span>
        </div>
        <p style="font-size:0.82em;color:#888;margin-bottom:12px" id="browser-desc">Chrome Extension · 操作任意 DApp 自动签名</p>
        <div id="browser-inactive">
          <div style="display:flex;gap:12px;margin-bottom:12px">
            <div style="flex:1">
              <label style="color:#888;font-size:0.85em" id="browser-time-label">⏱ 授权时间（分钟）</label>
              <input id="browser-time" type="number" value="30" min="0" style="width:100%;padding:8px;margin-top:4px;background:#222;color:#fff;border:1px solid #444;border-radius:6px">
            </div>
            <div style="flex:1">
              <label style="color:#888;font-size:0.85em" id="browser-signs-label">✍️ 签名次数上限</label>
              <input id="browser-signs" type="number" value="10" min="0" style="width:100%;padding:8px;margin-top:4px;background:#222;color:#fff;border:1px solid #444;border-radius:6px">
            </div>
          </div>
          <button class="btn" style="background:#7c3aed;padding:10px;font-size:1em" onclick="doStartSession('browser')" id="btn-connect-dapp">🌐 连接 DApp</button>
        </div>
        <div id="browser-active" style="display:none">
          <div style="display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:0.9em;margin-bottom:12px">
            <span style="color:#888" id="browser-addr-label2">📍 地址</span><span id="browser-addr" style="color:#fff;font-family:monospace;font-size:0.85em;word-break:break-all">-</span>
            <span style="color:#888" id="browser-signed-label">✍️ 已签名</span><span><span id="browser-count" style="color:#b388ff;font-weight:700">0</span> <span id="browser-limit" style="color:#666">/ ∞</span></span>
            <span style="color:#888" id="browser-remaining-label">⏱ 剩余时间</span><span id="browser-remaining" style="color:#fbbf24;font-weight:600">-</span>
          </div>
          <button class="btn btn-danger" style="padding:8px;background:#dc2626" onclick="doRevokeSession('browser')" id="btn-disconnect-dapp">🔒 断开 DApp</button>
        </div>
      </div>
    </div>
    <p style="font-size:0.78em;color:#555;margin-top:12px;text-align:center" id="session-hint">0 = 不限制 · 授权过期后 AI 无法签名 · 可随时撤销</p>
  </div>
</div>

<!-- Add Modal -->
<div class="overlay" id="add-overlay">
  <div class="modal">
    <h2 id="add-modal-title">🔐 添加新助记词钱包</h2>
    <div id="add-form">
      <div class="field">
        <label id="add-step1-label">步骤1: 输入助记词（BIP39，空格分隔）</label>
        <textarea id="inp-mnemonic" placeholder="abandon abandon abandon ..."></textarea>
        <button class="example-btn" onclick="document.getElementById('inp-mnemonic').value='abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about'" id="btn-fill-test">填入测试助记词</button>
      </div>
      <div class="field">
        <label id="add-step2-label">步骤2: 助记词昵称</label>
        <input type="text" id="inp-name" value="我的助记词" placeholder="给这个助记词起个名字">
      </div>
      <div class="modal-btns">
        <button class="btn btn-red" onclick="doGenerate()" id="btn-generate">🚀 生成钱包</button>
        <button class="btn" style="background:#666" onclick="closeAdd()" id="btn-add-cancel">取消</button>
      </div>
    </div>
    <div id="add-result" style="display:none"></div>
  </div>
</div>

<!-- Confirm Delete Modal -->
<div class="overlay" id="del-overlay">
  <div class="modal" style="max-width:400px">
    <h2 id="del-title">⚠️ 确认删除</h2>
    <p id="del-desc" style="margin:12px 0;color:#ccc">确定要删除 <strong id="del-name" style="color:var(--red)"></strong> 吗？</p>
    <p style="font-size:0.82em;color:var(--muted)" id="del-keychain-hint">此操作将同时删除 Keychain 中的助记词</p>
    <div class="modal-btns">
      <button class="btn btn-danger" onclick="doDelete()" id="btn-del-confirm">删除</button>
      <button class="btn" style="background:#666" onclick="closeDel()" id="btn-del-cancel">取消</button>
    </div>
  </div>
</div>

<div class="overlay" id="dapp-overlay">
  <div class="modal" style="max-width:480px">
    <h2 id="dapp-modal-title">🔗 连接 Sui DApp</h2>
    <div id="dapp-form">
      <label style="color:#aaa;font-size:0.9em" id="dapp-select-label">选择 Sui 钱包</label>
      <select id="dapp-wallet" style="width:100%;padding:10px;margin:8px 0 16px;background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:8px;font-size:0.95em">
        <option value="">加载中...</option>
      </select>
      <div style="display:flex;gap:12px">
        <div style="flex:1">
          <label style="color:#aaa;font-size:0.85em" id="dapp-time-label">授权时间（分钟，0=不限）</label>
          <input id="dapp-time" type="number" value="0" min="0" style="width:100%;padding:8px;margin:4px 0;background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:6px">
        </div>
        <div style="flex:1">
          <label style="color:#aaa;font-size:0.85em" id="dapp-signs-label">签名次数上限（0=不限）</label>
          <input id="dapp-signs" type="number" value="0" min="0" style="width:100%;padding:8px;margin:4px 0;background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:6px">
        </div>
      </div>
      <p style="font-size:0.8em;color:#888;margin:12px 0" id="dapp-hint">连接后在 Chrome 扩展中选择 MiaoWallet 即可使用 Sui DApp。关闭浏览器自动断开。</p>
      <div class="modal-btns">
        <button class="btn" style="background:#8b5cf6" onclick="doDappConnect()" id="btn-dapp-connect">🚀 连接</button>
        <button class="btn" style="background:#666" onclick="closeDapp()" id="btn-dapp-cancel">取消</button>
      </div>
    </div>
    <div id="dapp-status" style="display:none">
      <div style="padding:16px;background:#1a3a1a;border-radius:8px;margin:12px 0">
        <p style="color:#4ade80;font-weight:bold;margin:0 0 8px" id="dapp-connected-text">✅ 已连接</p>
        <p style="color:#aaa;font-size:0.9em;margin:4px 0"><span id="dapp-addr-label">地址:</span> <span id="dapp-addr" style="color:#fff;font-family:monospace;font-size:0.85em"></span></p>
        <p style="color:#aaa;font-size:0.9em;margin:4px 0"><span id="dapp-signed-label">已签名:</span> <span id="dapp-count" style="color:#fff">0</span> <span id="dapp-times-label">次</span></p>
        <p style="color:#aaa;font-size:0.9em;margin:4px 0" id="dapp-limit-info"></p>
      </div>
      <div class="modal-btns">
        <button class="btn btn-danger" onclick="doDappDisconnect()" id="btn-dapp-disconnect">断开连接</button>
        <button class="btn" style="background:#666" onclick="closeDapp()" id="btn-dapp-close">关闭</button>
      </div>
    </div>
  </div>
</div>

<!-- Whitelist Modal -->
<div class="overlay" id="wl-overlay">
  <div class="modal" style="max-width:560px">
    <h2 id="wl-title">🛡 白名单管理</h2>
    <div style="margin-bottom:16px">
      <h3 style="font-size:0.95em;margin-bottom:8px;color:#4ade80" id="wl-origin-title">🌐 允许的 DApp（Origin 白名单）</h3>
      <p style="font-size:0.78em;color:#888;margin-bottom:8px" id="wl-origin-desc">只有白名单中的网站可以发起签名请求</p>
      <div id="wl-origins-list" style="margin-bottom:8px"></div>
      <div style="display:flex;gap:8px">
        <input id="wl-origin-input" type="text" placeholder="https://example.com" style="flex:1;padding:8px;background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:6px;font-size:0.9em">
        <button class="btn btn-sm btn-green" style="padding:8px 16px" onclick="addOrigin()" id="btn-wl-add-origin">添加</button>
      </div>
    </div>
    <div style="margin-bottom:16px">
      <h3 style="font-size:0.95em;margin-bottom:8px;color:#60a5fa" id="wl-contract-title">📜 允许的合约（Contract 白名单）</h3>
      <p style="font-size:0.78em;color:#888;margin-bottom:8px" id="wl-contract-desc">只能与白名单中的合约交互。留空则不限制。</p>
      <div id="wl-contracts-list" style="margin-bottom:8px"></div>
      <div style="display:flex;gap:8px">
        <input id="wl-contract-input" type="text" placeholder="0x1234...合约地址" style="flex:1;padding:8px;background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:6px;font-size:0.9em">
        <button class="btn btn-sm btn-blue" style="padding:8px 16px" onclick="addContract()" id="btn-wl-add-contract">添加</button>
      </div>
    </div>
    <div class="modal-btns">
      <button class="btn" style="background:#666" onclick="closeWhitelist()" id="btn-wl-close">关闭</button>
    </div>
  </div>
</div>

<script>
const i18n = {
  zh: {
    title: '🔐 MiaoWallet Pro', ready: '就绪', loading: '加载中...',
    walletList: '📋 钱包列表', features: '🚀 功能',
    newMnemonic: '➕ 新助记词', refresh: '🔄 刷新',
    connectDapp: '🔗 连接 Sui DApp', playRps: '🎮 来玩剪刀石头布',
    resetKeychain: '🔓 重置 Keychain 授权', supportUs: '💜 支持我们',
    whitelist: '🛡 白名单管理',
    guide: '📖 使用说明',
    guide1: '1. 点击「新助记词」添加钱包',
    guide2: '2. 输入 BIP39 助记词（12/24词）',
    guide3: '3. 自动生成 SUI / Solana / Ethereum 地址',
    guide4: '4. 助记词安全存储到 macOS Keychain',
    guideTip1: '点击钱包名展开/折叠地址',
    guideTip2: '点击 📋 复制地址',
    emptyWallet: '暂无钱包，点击「新助记词」添加',
    loaded: '已加载 {0} 个助记词，{1} 个钱包',
    walletCount: '{0} 钱包', chainCount: '{0} 链',
    copied: '✅ 地址已复制',
    addTitle: '🔐 添加新助记词钱包',
    step1: '步骤1: 输入助记词（BIP39，空格分隔）',
    step2: '步骤2: 助记词昵称',
    fillTest: '填入测试助记词',
    generate: '🚀 生成钱包', cancel: '取消',
    generating: '⏳ 正在生成...',
    genSuccess: '✅ 助记词「{0}」生成成功！', done: '完成',
    enterMnemonic: '请输入助记词', enterNickname: '请输入助记词昵称',
    confirmDeleteWallet: '⚠️ 确认删除钱包',
    confirmDeleteMnemonic: '⚠️ 确认删除助记词',
    deleteWalletDesc: '确定要删除钱包「{0}」及其所有链地址吗？',
    deleteMnemonicDesc: '确定要删除助记词「{0}」及其所有钱包吗？此操作不可恢复！',
    deleteKeychainNote: '此操作将同时删除 Keychain 中的助记词',
    delete: '删除',
    deleted: '已删除钱包: {0}', deletedMnemonic: '已删除助记词: {0}',
    deleteFail: '删除失败: ',
    genNewBip44: '确定要从助记词「{0}」生成下一个钱包吗？\n\nBIP44标准模式：将自动按顺序生成新钱包。',
    genNewOld: '为助记词「{0}」生成新钱包\n请输入钱包名称（建议包含时间戳）:',
    genNewConfirm: '确定要从助记词「{0}」生成新钱包「{1}」吗？',
    genNewSuccess: '✅ 新钱包「{0}」生成成功！',
    genNewFail: '❌ 生成失败: ',
    renamePrompt: '请输入新的钱包名称 (当前: {0}):',
    renameConfirm: '确定要将钱包 "{0}" 改名为 "{1}" 吗？',
    renamed: '已改名: {0} → {1}',
    renameFail: '改名失败: ',
    renameMnemonicPrompt: '请输入新的助记词昵称 (当前: {0}):',
    renameMnemonicConfirm: '确定要将助记词昵称 "{0}" 改为 "{1}" 吗？',
    renamedMnemonic: '已修改助记词昵称: {0}',
    renameMnemonicFail: '修改失败: ',
    dappTitle: '🔗 连接 Sui DApp',
    dappSelectWallet: '选择 Sui 钱包',
    dappLoading: '加载中...',
    dappNoWallet: '没有 Sui 钱包，请先添加',
    dappAuthTime: '授权时间（分钟，0=不限）',
    dappAuthSigns: '签名次数上限（0=不限）',
    dappNote: '连接后在 Chrome 扩展中选择 MiaoWallet 即可使用 Sui DApp。关闭浏览器自动断开。',
    dappConnect: '🚀 连接', dappDisconnect: '断开连接', close: '关闭',
    dappConnected: '✅ 已连接', dappAddr: '地址: ', dappSigned: '已签名: ',
    dappTimes: ' 次', dappSignLimit: '次数限制: ', dappRemaining: '剩余: ',
    dappMinutes: ' 分钟', dappNoLimit: '无限制',
    dappSelectFirst: '请选择钱包', dappConnectFail: '连接失败: ',
    resetKeychainConfirm: '确定要重置 Keychain 授权吗？\n\n重置后下次操作钱包时会重新弹出系统授权弹窗。',
    resetKeychainSuccess: '✅ Keychain 授权已重置',
    resetKeychainFail: '❌ 重置失败: ',
    mnemonicNameEmpty: '助记词昵称不能为空',
    myWallet: '我的助记词',
    // Session panel
    sessionTitle: '签名授权 Session',
    sessionWalletLabel: '钱包:',
    sessionLoading: '加载中...',
    sessionNoWallet: '没有 Sui 钱包，请先添加',
    sessionSelectFirst: '请先选择钱包',
    sessionAuthFail: '授权失败: ',
    apiBadgeActive: '已授权',
    apiBadgeInactive: '未授权',
    browserBadgeActive: '已连接',
    browserBadgeInactive: '未连接',
    apiDesc: 'MCP Server · AI Agent 通过命令自动签名',
    browserDesc: 'Chrome Extension · 操作任意 DApp 自动签名',
    authTimeLabel: '⏱ 授权时间（分钟）',
    signLimitLabel: '✍️ 签名次数上限',
    authApiBtn: '⚡ 授权 API',
    revokeApiBtn: '🔒 撤销 API 授权',
    connectDappBtn: '🌐 连接 DApp',
    disconnectDappBtn: '🔒 断开 DApp',
    addrLabel: '📍 地址',
    signedLabel: '✍️ 已签名',
    remainingLabel: '⏱ 剩余时间',
    sessionHint: '0 = 不限制 · 授权过期后 AI 无法签名 · 可随时撤销',
    noTimeLimit: '不限时',
    expired: '已过期',
    // renderTree
    walletCountLabel: '{0} 钱包',
    chainCountLabel: '{0} 链',
    genNewWalletTitle: '生成新钱包',
    renameNicknameTitle: '修改昵称',
    copyTitle: '复制',
    balanceLoading: '💰 加载余额中...',
    balanceNone: '💰 无余额',
    balanceFail: '⚠️ 查询失败',
    // Whitelist
    wlTitle: '🛡 白名单管理',
    wlOriginTitle: '🌐 允许的 DApp（Origin 白名单）',
    wlOriginDesc: '只有白名单中的网站可以发起签名请求',
    wlContractTitle: '📜 允许的合约（Contract 白名单）',
    wlContractDesc: '只能与白名单中的合约交互。留空则不限制。',
    wlAdd: '添加',
    wlClose: '关闭',
    wlEmpty: '暂无',
    wlEmptyContract: '暂无（不限制合约）',
    wlAddFail: '添加失败',
    wlRemoveFail: '移除失败',
    wlConfirmRemoveOrigin: '确定移除 {0} ？',
    wlConfirmRemoveContract: '确定移除合约 {0}... ？',
    wlOriginPlaceholder: 'https://example.com',
    wlContractPlaceholder: '0x1234...合约地址',
  },
  en: {
    title: '🔐 MiaoWallet Pro', ready: 'Ready', loading: 'Loading...',
    walletList: '📋 Wallets', features: '🚀 Features',
    newMnemonic: '➕ New Mnemonic', refresh: '🔄 Refresh',
    connectDapp: '🔗 Connect Sui DApp', playRps: '🎮 Play RPS Game',
    resetKeychain: '🔓 Reset Keychain Auth', supportUs: '💜 Support Us',
    whitelist: '🛡 Whitelist',
    guide: '📖 Guide',
    guide1: '1. Click "New Mnemonic" to add wallet',
    guide2: '2. Enter BIP39 mnemonic (12/24 words)',
    guide3: '3. Auto-generate SUI / Solana / Ethereum addresses',
    guide4: '4. Mnemonic stored securely in macOS Keychain',
    guideTip1: 'Click wallet name to expand/collapse',
    guideTip2: 'Click 📋 to copy address',
    emptyWallet: 'No wallets yet. Click "New Mnemonic" to add.',
    loaded: 'Loaded {0} mnemonics, {1} wallets',
    walletCount: '{0} wallets', chainCount: '{0} chains',
    copied: '✅ Address copied',
    addTitle: '🔐 Add New Mnemonic Wallet',
    step1: 'Step 1: Enter mnemonic (BIP39, space-separated)',
    step2: 'Step 2: Mnemonic nickname',
    fillTest: 'Fill test mnemonic',
    generate: '🚀 Generate', cancel: 'Cancel',
    generating: '⏳ Generating...',
    genSuccess: '✅ Mnemonic "{0}" generated!', done: 'Done',
    enterMnemonic: 'Please enter mnemonic', enterNickname: 'Please enter nickname',
    confirmDeleteWallet: '⚠️ Confirm Delete Wallet',
    confirmDeleteMnemonic: '⚠️ Confirm Delete Mnemonic',
    deleteWalletDesc: 'Delete wallet "{0}" and all its chain addresses?',
    deleteMnemonicDesc: 'Delete mnemonic "{0}" and all its wallets? This cannot be undone!',
    deleteKeychainNote: 'This will also remove the mnemonic from Keychain',
    delete: 'Delete',
    deleted: 'Deleted wallet: {0}', deletedMnemonic: 'Deleted mnemonic: {0}',
    deleteFail: 'Delete failed: ',
    genNewBip44: 'Generate next wallet from mnemonic "{0}"?\n\nBIP44 mode: will auto-generate sequentially.',
    genNewOld: 'Generate new wallet from mnemonic "{0}"\nEnter wallet name:',
    genNewConfirm: 'Generate new wallet "{1}" from mnemonic "{0}"?',
    genNewSuccess: '✅ New wallet "{0}" generated!',
    genNewFail: '❌ Generation failed: ',
    renamePrompt: 'Enter new wallet name (current: {0}):',
    renameConfirm: 'Rename wallet "{0}" to "{1}"?',
    renamed: 'Renamed: {0} → {1}',
    renameFail: 'Rename failed: ',
    renameMnemonicPrompt: 'Enter new mnemonic nickname (current: {0}):',
    renameMnemonicConfirm: 'Rename mnemonic "{0}" to "{1}"?',
    renamedMnemonic: 'Mnemonic renamed: {0}',
    renameMnemonicFail: 'Rename failed: ',
    dappTitle: '🔗 Connect Sui DApp',
    dappSelectWallet: 'Select Sui Wallet',
    dappLoading: 'Loading...',
    dappNoWallet: 'No Sui wallet. Please add one first.',
    dappAuthTime: 'Auth time (min, 0=unlimited)',
    dappAuthSigns: 'Max signatures (0=unlimited)',
    dappNote: 'After connecting, select MiaoWallet in Chrome extension to use Sui DApps. Auto-disconnects when browser closes.',
    dappConnect: '🚀 Connect', dappDisconnect: 'Disconnect', close: 'Close',
    dappConnected: '✅ Connected', dappAddr: 'Address: ', dappSigned: 'Signed: ',
    dappTimes: ' times', dappSignLimit: 'Sign limit: ', dappRemaining: 'Remaining: ',
    dappMinutes: ' min', dappNoLimit: 'Unlimited',
    dappSelectFirst: 'Please select a wallet', dappConnectFail: 'Connect failed: ',
    resetKeychainConfirm: 'Reset Keychain authorization?\n\nYou will need to re-authorize next time you access wallets.',
    resetKeychainSuccess: '✅ Keychain auth reset',
    resetKeychainFail: '❌ Reset failed: ',
    mnemonicNameEmpty: 'Mnemonic nickname cannot be empty',
    myWallet: 'My Mnemonic',
    // Session panel
    sessionTitle: 'Signing Session',
    sessionWalletLabel: 'Wallet:',
    sessionLoading: 'Loading...',
    sessionNoWallet: 'No Sui wallet. Please add one first.',
    sessionSelectFirst: 'Please select a wallet',
    sessionAuthFail: 'Auth failed: ',
    apiBadgeActive: 'Authorized',
    apiBadgeInactive: 'Unauthorized',
    browserBadgeActive: 'Connected',
    browserBadgeInactive: 'Disconnected',
    apiDesc: 'MCP Server · AI Agent auto-signs via commands',
    browserDesc: 'Chrome Extension · Auto-sign on any DApp',
    authTimeLabel: '⏱ Auth time (min)',
    signLimitLabel: '✍️ Max signatures',
    authApiBtn: '⚡ Authorize API',
    revokeApiBtn: '🔒 Revoke API Auth',
    connectDappBtn: '🌐 Connect DApp',
    disconnectDappBtn: '🔒 Disconnect DApp',
    addrLabel: '📍 Address',
    signedLabel: '✍️ Signed',
    remainingLabel: '⏱ Remaining',
    sessionHint: '0 = unlimited · AI cannot sign after expiry · revoke anytime',
    noTimeLimit: 'Unlimited',
    expired: 'Expired',
    // renderTree
    walletCountLabel: '{0} wallets',
    chainCountLabel: '{0} chains',
    genNewWalletTitle: 'Generate new wallet',
    renameNicknameTitle: 'Rename',
    copyTitle: 'Copy',
    balanceLoading: '💰 Loading balances...',
    balanceNone: '💰 No balance',
    balanceFail: '⚠️ Query failed',
    // Whitelist
    wlTitle: '🛡 Whitelist',
    wlOriginTitle: '🌐 Allowed DApps (Origin Whitelist)',
    wlOriginDesc: 'Only whitelisted websites can initiate signing requests',
    wlContractTitle: '📜 Allowed Contracts (Contract Whitelist)',
    wlContractDesc: 'Can only interact with whitelisted contracts. Leave empty for no restriction.',
    wlAdd: 'Add',
    wlClose: 'Close',
    wlEmpty: 'None',
    wlEmptyContract: 'None (no contract restriction)',
    wlAddFail: 'Add failed',
    wlRemoveFail: 'Remove failed',
    wlConfirmRemoveOrigin: 'Remove {0}?',
    wlConfirmRemoveContract: 'Remove contract {0}...?',
    wlOriginPlaceholder: 'https://example.com',
    wlContractPlaceholder: '0x1234...contract address',
  }
};

let lang = (navigator.language || '').startsWith('zh') ? 'zh' : 'en';
const savedLang = localStorage.getItem('miaowallet-lang');
if (savedLang) lang = savedLang;

function t(key) { return (i18n[lang] && i18n[lang][key]) || key; }
function tf(key, ...args) { let s = t(key); args.forEach((a,i) => { s = s.replace('{'+i+'}', a); }); return s; }

function toggleLang() {
  lang = lang === 'zh' ? 'en' : 'zh';
  localStorage.setItem('miaowallet-lang', lang);
  updateStaticUI();
  refreshTree();
}

function updateStaticUI() {
  document.getElementById('header-title').textContent = t('title');
  document.getElementById('lang-btn').textContent = lang === 'zh' ? '中/EN' : 'EN/中';
  document.getElementById('status').textContent = t('ready');
  // Left panel
  document.getElementById('wallet-list-title').textContent = t('walletList');
  // Right panel
  document.getElementById('func-title').textContent = t('features');
  document.getElementById('btn-add').textContent = t('newMnemonic');
  document.getElementById('btn-refresh').textContent = t('refresh');
  document.getElementById('btn-rps').textContent = t('playRps');
  document.getElementById('btn-whitelist').textContent = t('whitelist');
  document.getElementById('btn-reset-keychain').textContent = t('resetKeychain');
  document.getElementById('btn-support').textContent = t('supportUs');
  // Guide
  document.getElementById('info-title').innerHTML = t('guide');
  var guideHtml = t('guide1') + '<br>' + t('guide2') + '<br>' + t('guide3') + '<br>' + t('guide4') +
    '<br><br>' + t('guideTip1') + '<br>' + t('guideTip2');
  document.getElementById('info-title').nextSibling.nextSibling.textContent = '';
  document.getElementById('info-title').parentElement.innerHTML = '<strong id="info-title">' + t('guide') + '</strong><br><br>' + guideHtml;
  // Add modal
  document.getElementById('add-modal-title').textContent = t('addTitle');
  document.getElementById('add-step1-label').textContent = t('step1');
  document.getElementById('add-step2-label').textContent = t('step2');
  document.getElementById('btn-generate').textContent = t('generate');
  document.getElementById('btn-add-cancel').textContent = t('cancel');
  // Delete modal
  document.getElementById('btn-del-confirm').textContent = t('delete');
  document.getElementById('btn-del-cancel').textContent = t('cancel');
  // Session panel i18n
  var sp = document.getElementById('session-panel-title');
  if (sp) sp.textContent = t('sessionTitle');
  var swl = document.getElementById('session-wallet-label');
  if (swl) swl.textContent = t('sessionWalletLabel');
  // API mode
  var apiDesc = document.getElementById('api-desc');
  if (apiDesc) apiDesc.textContent = t('apiDesc');
  var apiTimeLabel = document.getElementById('api-time-label');
  if (apiTimeLabel) apiTimeLabel.textContent = t('authTimeLabel');
  var apiSignsLabel = document.getElementById('api-signs-label');
  if (apiSignsLabel) apiSignsLabel.textContent = t('signLimitLabel');
  var btnAuthApi = document.getElementById('btn-auth-api');
  if (btnAuthApi) btnAuthApi.textContent = t('authApiBtn');
  var btnRevokeApi = document.getElementById('btn-revoke-api');
  if (btnRevokeApi) btnRevokeApi.textContent = t('revokeApiBtn');
  var apiAddrLabel2 = document.getElementById('api-addr-label2');
  if (apiAddrLabel2) apiAddrLabel2.textContent = t('addrLabel');
  var apiSignedLabel = document.getElementById('api-signed-label');
  if (apiSignedLabel) apiSignedLabel.textContent = t('signedLabel');
  var apiRemainingLabel = document.getElementById('api-remaining-label');
  if (apiRemainingLabel) apiRemainingLabel.textContent = t('remainingLabel');
  // Browser mode
  var browserDesc = document.getElementById('browser-desc');
  if (browserDesc) browserDesc.textContent = t('browserDesc');
  var browserTimeLabel = document.getElementById('browser-time-label');
  if (browserTimeLabel) browserTimeLabel.textContent = t('authTimeLabel');
  var browserSignsLabel = document.getElementById('browser-signs-label');
  if (browserSignsLabel) browserSignsLabel.textContent = t('signLimitLabel');
  var btnConnectDapp = document.getElementById('btn-connect-dapp');
  if (btnConnectDapp) btnConnectDapp.textContent = t('connectDappBtn');
  var btnDisconnectDapp = document.getElementById('btn-disconnect-dapp');
  if (btnDisconnectDapp) btnDisconnectDapp.textContent = t('disconnectDappBtn');
  var browserAddrLabel2 = document.getElementById('browser-addr-label2');
  if (browserAddrLabel2) browserAddrLabel2.textContent = t('addrLabel');
  var browserSignedLabel = document.getElementById('browser-signed-label');
  if (browserSignedLabel) browserSignedLabel.textContent = t('signedLabel');
  var browserRemainingLabel = document.getElementById('browser-remaining-label');
  if (browserRemainingLabel) browserRemainingLabel.textContent = t('remainingLabel');
  // Session hint
  var sessionHint = document.getElementById('session-hint');
  if (sessionHint) sessionHint.textContent = t('sessionHint');
  // Whitelist modal
  var wlTitle = document.getElementById('wl-title');
  if (wlTitle) wlTitle.textContent = t('wlTitle');
  var wlOriginTitle = document.getElementById('wl-origin-title');
  if (wlOriginTitle) wlOriginTitle.textContent = t('wlOriginTitle');
  var wlOriginDesc = document.getElementById('wl-origin-desc');
  if (wlOriginDesc) wlOriginDesc.textContent = t('wlOriginDesc');
  var wlContractTitle = document.getElementById('wl-contract-title');
  if (wlContractTitle) wlContractTitle.textContent = t('wlContractTitle');
  var wlContractDesc = document.getElementById('wl-contract-desc');
  if (wlContractDesc) wlContractDesc.textContent = t('wlContractDesc');
  var btnWlAddOrigin = document.getElementById('btn-wl-add-origin');
  if (btnWlAddOrigin) btnWlAddOrigin.textContent = t('wlAdd');
  var btnWlAddContract = document.getElementById('btn-wl-add-contract');
  if (btnWlAddContract) btnWlAddContract.textContent = t('wlAdd');
  var btnWlClose = document.getElementById('btn-wl-close');
  if (btnWlClose) btnWlClose.textContent = t('wlClose');
  // Whitelist placeholders
  var wlOriginInput = document.getElementById('wl-origin-input');
  if (wlOriginInput) wlOriginInput.placeholder = t('wlOriginPlaceholder');
  var wlContractInput = document.getElementById('wl-contract-input');
  if (wlContractInput) wlContractInput.placeholder = t('wlContractPlaceholder');
  // Update badges based on current state
  var apiBadge = document.getElementById('api-badge');
  if (apiBadge) {
    var isApiActive = document.getElementById('api-active').style.display !== 'none';
    apiBadge.textContent = isApiActive ? t('apiBadgeActive') : t('apiBadgeInactive');
  }
  var browserBadge = document.getElementById('browser-badge');
  if (browserBadge) {
    var isBrowserActive = document.getElementById('browser-active').style.display !== 'none';
    browserBadge.textContent = isBrowserActive ? t('browserBadgeActive') : t('browserBadgeInactive');
  }
}

async function resetKeychainAuth() {
  if (!confirm(t('resetKeychainConfirm'))) return;
  const data = await api('reset_keychain_auth', {});
  if (data.ok) {
    document.getElementById('status').textContent = t('resetKeychainSuccess');
    refreshTree();
  } else {
    alert(t('resetKeychainFail') + (data.error || ''));
  }
}

let walletData = {};

async function api(path, body) {
  const r = await fetch('/api/' + path, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body || {})
  });
  return r.json();
}

function chainClass(c) {
  const l = c.toLowerCase();
  if (l === 'sui') return 'sui';
  if (l === 'solana') return 'solana';
  if (l === 'ethereum') return 'ethereum';
  return 'unknown';
}

function copyAddr(addr) {
  navigator.clipboard.writeText(addr).then(() => {
    document.getElementById('status').textContent = t('copied');
    setTimeout(() => document.getElementById('status').textContent = t('ready'), 2000);
  });
}

function renderTree(data) {
  walletData = data;
  const container = document.getElementById('wallet-tree');
  const mnemonicHashes = Object.keys(data);

  if (mnemonicHashes.length === 0) {
    container.innerHTML = '<div class="tree-empty">' + t('emptyWallet') + '</div>';
    document.getElementById('status').textContent = t('ready');
    return;
  }

  let html = '';
  let totalWallets = 0;
  
  for (const mnemonicHash of mnemonicHashes) {
    const mnemonicData = data[mnemonicHash];
    const mnemonicPreview = mnemonicData.mnemonic_preview || "助记词...";
    const wallets = mnemonicData.wallets || {};
    const walletNames = Object.keys(wallets);
    totalWallets += walletNames.length;
    
    html += `<div class="mnemonic-node">
      <div class="mnemonic-header" onclick="toggleMnemonic(this)">
        <span class="arrow">▶</span>
        <span class="name">🔐 ${esc(mnemonicPreview)}</span>
        <span class="count">${tf('walletCountLabel', walletNames.length)}</span>
        <button class="btn btn-sm btn-green" onclick="event.stopPropagation(); generateNewWalletFromMnemonic('${esc(mnemonicHash)}', '${esc(mnemonicPreview)}')" title="${t('genNewWalletTitle')}">➕</button>
        <button class="btn btn-sm btn-warning" onclick="event.stopPropagation(); renameMnemonic('${esc(mnemonicHash)}', '${esc(mnemonicPreview)}')" title="${t('renameNicknameTitle')}">✏️</button>
        <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); confirmDeleteMnemonic('${esc(mnemonicHash)}', '${esc(mnemonicPreview)}')">🗑</button>
      </div>
      <div class="mnemonic-children">`;
    
    for (const walletName of walletNames) {
      const chains = wallets[walletName];
      const chainKeys = Object.keys(chains);
      html += `<div class="wallet-node">
        <div class="wallet-header" onclick="toggleWallet(this)">
          <span class="arrow">▶</span>
          <span class="name">📁 ${esc(walletName)}</span>
          <span class="count">${tf('chainCountLabel', chainKeys.length)}</span>
          <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); renameWallet('${esc(walletName)}')" title="${t('renameNicknameTitle')}">✏️</button>
          <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); confirmDelete('${esc(walletName)}')">🗑</button>
        </div>
        <div class="wallet-children">`;
      for (const chain of chainKeys) {
        const addr = chains[chain];
        html += `<div class="chain-row">
          <span class="chain-tag ${chainClass(chain)}">${esc(chain)}</span>
          <span class="chain-addr">${esc(addr)}</span>
          <span class="chain-copy" onclick="copyAddr('${esc(addr)}')" title="${t('copyTitle')}">📋</span>
        </div>`;
        if (chain.toLowerCase() === 'sui') {
          html += `<div class="balance-row" id="bal-${esc(addr).slice(0,16)}" data-addr="${esc(addr)}">
            <span class="balance-loading">${t('balanceLoading')}</span>
          </div>`;
        }
      }
      html += '</div></div>';
    }
    html += '</div></div>';
  }
  
  container.innerHTML = html;
  document.getElementById('status').textContent = tf('loaded', mnemonicHashes.length, totalWallets);
  // Auto-load balances for all Sui addresses
  loadAllBalances();
}

async function loadAllBalances() {
  const rows = document.querySelectorAll('.balance-row[data-addr]');
  for (const row of rows) {
    const addr = row.dataset.addr;
    try {
      const r = await fetch('/api/balances', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({address: addr})
      });
      const data = await r.json();
      if (data.ok && data.balances && data.balances.length > 0) {
        row.innerHTML = data.balances.map(b =>
          `<span class="balance-tag">${b.icon} ${b.symbol} <span class="bal-amount">${b.amount}</span></span>`
        ).join('');
      } else {
        row.innerHTML = '<span class="balance-tag">' + t('balanceNone') + '</span>';
      }
    } catch(e) {
      row.innerHTML = '<span class="balance-loading">' + t('balanceFail') + '</span>';
    }
  }
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function toggleNode(el) {
  el.classList.toggle('expanded');
  const children = el.nextElementSibling;
  children.classList.toggle('show');
}

// 支持助记词节点和钱包节点的切换
function toggleMnemonic(el) {
  toggleNode(el);
}

function toggleWallet(el) {
  toggleNode(el);
}

async function refreshTree() {
  const data = await api('wallets_tree');
  renderTree(data.tree || {});
  // 同时刷新 Session 状态
  await checkAllSessions();
}

// Add modal
function openAddModal() {
  document.getElementById('add-overlay').classList.add('active');
  document.getElementById('add-form').style.display = '';
  document.getElementById('add-result').style.display = 'none';
  document.getElementById('inp-mnemonic').value = '';
  document.getElementById('inp-name').value = 'my_wallet_1';
}
function closeAdd() { document.getElementById('add-overlay').classList.remove('active'); }

async function doGenerate() {
  const mnemonic = document.getElementById('inp-mnemonic').value.trim();
  const mnemonicNickname = document.getElementById('inp-name').value.trim();
  if (!mnemonic) { alert(t('enterMnemonic')); return; }
  if (!mnemonicNickname) { alert(t('enterNickname')); return; }

  document.getElementById('add-form').style.display = 'none';
  const res = document.getElementById('add-result');
  res.style.display = '';
  res.innerHTML = '<div class="msg msg-ok">' + t('generating') + '</div>';

  const data = await api('generate', { mnemonic, mnemonic_nickname: mnemonicNickname });
  if (data.error) {
    res.innerHTML = `<div class="msg msg-err">❌ ${esc(data.error)}</div>
      <div class="modal-btns"><button class="btn" style="background:#666" onclick="openAddModal()">${t('refresh')}</button>
      <button class="btn" style="background:#444" onclick="closeAdd()">${t('close')}</button></div>`;
    return;
  }

  let lines = '';
  for (const [c, a] of Object.entries(data.wallets)) {
    lines += `<div class="addr-line"><span class="r-chain">${esc(c)}:</span> <span class="r-addr">${esc(a)}</span></div>`;
  }
  res.innerHTML = `<div class="msg msg-ok">${tf('genSuccess', esc(mnemonicNickname))}</div>
    <div class="result-box">${lines}</div>
    <div class="modal-btns" style="margin-top:14px">
      <button class="btn btn-green" onclick="closeAdd(); refreshTree();">${t('done')}</button></div>`;
}

// Delete
let pendingDelete = null;
let pendingDeleteMnemonic = null;

function confirmDelete(name) {
  pendingDelete = name;
  pendingDeleteMnemonic = null;
  document.getElementById('del-name').textContent = name;
  document.getElementById('del-title').textContent = t('confirmDeleteWallet');
  document.getElementById('del-desc').textContent = tf('deleteWalletDesc', name);
  document.getElementById('del-overlay').classList.add('active');
}

function confirmDeleteMnemonic(mnemonicHash, mnemonicPreview) {
  pendingDelete = null;
  pendingDeleteMnemonic = {hash: mnemonicHash, preview: mnemonicPreview};
  document.getElementById('del-name').textContent = mnemonicPreview;
  document.getElementById('del-title').textContent = t('confirmDeleteMnemonic');
  document.getElementById('del-desc').textContent = tf('deleteMnemonicDesc', mnemonicPreview);
  document.getElementById('del-overlay').classList.add('active');
}

function closeDel() { 
  document.getElementById('del-overlay').classList.remove('active'); 
  pendingDelete = null;
  pendingDeleteMnemonic = null;
}

// 从已有助记词生成新钱包 (BIP44标准模式)
function generateNewWalletFromMnemonic(mnemonicHash, mnemonicPreview) {
  // 先检查是否是BIP44模式
  checkBIP44Mode().then(isBIP44Mode => {
    if (isBIP44Mode) {
      // BIP44模式：自动生成，只需确认
      if (confirm(`确定要从助记词「${mnemonicPreview}」生成下一个钱包吗？\n\nBIP44标准模式：将自动按顺序生成新钱包。`)) {
        doGenerateFromMnemonicBIP44(mnemonicHash, mnemonicPreview);
      }
    } else {
      // 旧模式：需要用户输入名称
      const walletName = prompt(`为助记词「${mnemonicPreview}」生成新钱包\n请输入钱包名称（建议包含时间戳）:`, `${mnemonicPreview}_${Date.now().toString().slice(-6)}`);
      
      if (walletName && walletName.trim() !== '') {
        const trimmedName = walletName.trim();
        if (confirm(`确定要从助记词「${mnemonicPreview}」生成新钱包「${trimmedName}」吗？`)) {
          doGenerateFromMnemonic(mnemonicHash, trimmedName);
        }
      }
    }
  }).catch(error => {
    console.error("检查BIP44模式失败:", error);
    // 默认使用BIP44模式
    if (confirm(`确定要从助记词「${mnemonicPreview}」生成下一个钱包吗？\n\nBIP44标准模式：将自动按顺序生成新钱包。`)) {
      doGenerateFromMnemonicBIP44(mnemonicHash, mnemonicPreview);
    }
  });
}

// 检查是否是BIP44模式
async function checkBIP44Mode() {
  try {
    // 直接调用API检查BIP44模式
    const data = await api('check_bip44_mode', {});
    return data.bip44_mode || false;
  } catch (error) {
    console.error("检查BIP44模式时出错:", error);
    return true; // 默认使用BIP44模式
  }
}

async function doGenerateFromMnemonic(mnemonicHash, walletName) {
  const data = await api('generate_from_mnemonic', { 
    mnemonic_hash: mnemonicHash,
    wallet_name: walletName
  });
  
  if (data.ok) {
    alert(`✅ 新钱包「${data.wallet_name || walletName}」生成成功！${data.bip44_mode ? '\n(BIP44标准模式)' : ''}`);
    refreshTree();
  } else {
    alert(`❌ 生成失败: ${data.error}`);
  }
}

// BIP44模式：自动生成下一个钱包
async function doGenerateFromMnemonicBIP44(mnemonicHash, mnemonicPreview) {
  const data = await api('generate_from_mnemonic', { 
    mnemonic_hash: mnemonicHash,
    wallet_name: '', // 空名称表示自动生成
    account_index: 0,
    address_index: null // null表示自动计算下一个索引
  });
  
  if (data.ok) {
    alert(`✅ 新钱包「${data.wallet_name}」生成成功！\n\nBIP44标准模式：\n- 钱包名称: ${data.wallet_name}\n- 自动按顺序生成\n- 符合行业标准`);
    refreshTree();
  } else {
    alert(`❌ 生成失败: ${data.error}`);
  }
}

// 钱包改名功能
let pendingRename = null;

function renameWallet(walletName) {
  pendingRename = walletName;
  const newName = prompt(`请输入新的钱包名称 (当前: ${walletName}):`, walletName);
  
  if (newName && newName !== walletName && newName.trim() !== '') {
    const trimmedName = newName.trim();
    if (confirm(`确定要将钱包 "${walletName}" 改名为 "${trimmedName}" 吗？`)) {
      doRename(walletName, trimmedName);
    }
  }
  pendingRename = null;
}

async function doRename(oldName, newName) {
  const data = await api('rename_wallet', { 
    old_name: oldName,
    new_name: newName
  });
  
  if (data.ok) {
    document.getElementById('status').textContent = tf('renamed', oldName, newName);
    refreshTree();
  } else {
    alert(t('renameFail') + (data.error || ''));
  }
}

// 修改助记词昵称功能
function renameMnemonic(mnemonicHash, currentName) {
  const newName = prompt(`请输入新的助记词昵称 (当前: ${currentName}):`, currentName);
  
  if (newName && newName !== currentName && newName.trim() !== '') {
    const trimmedName = newName.trim();
    if (confirm(tf('renameMnemonicConfirm', currentName, trimmedName))) {
      doRenameMnemonic(mnemonicHash, trimmedName);
    }
  }
}

async function doRenameMnemonic(mnemonicHash, newName) {
  const data = await api('rename_mnemonic', { 
    mnemonic_hash: mnemonicHash,
    new_name: newName
  });
  
  if (data.ok) {
    document.getElementById('status').textContent = tf('renamedMnemonic', newName);
    refreshTree();
  } else {
    alert(t('renameMnemonicFail') + (data.error || ''));
  }
}

async function doDelete() {
  if (pendingDelete) {
    // 删除钱包
    const data = await api('delete', { name: pendingDelete });
    closeDel();
    if (data.ok) {
      document.getElementById('status').textContent = tf('deleted', pendingDelete);
    } else {
      alert(t('deleteFail') + (data.error || ''));
    }
  } else if (pendingDeleteMnemonic) {
    // 删除助记词
    const data = await api('delete_mnemonic', { 
      mnemonic_hash: pendingDeleteMnemonic.hash,
      mnemonic_preview: pendingDeleteMnemonic.preview
    });
    closeDel();
    if (data.ok) {
      document.getElementById('status').textContent = tf('deletedMnemonic', pendingDeleteMnemonic.preview);
    } else {
      alert(t('deleteFail') + (data.error || ''));
    }
  }
  refreshTree();
}

// Init
updateStaticUI();
refreshTree();
loadSessionWallets();
checkAllSessions();

// ─── Session Management ───
let sessionTimers = {api: null, browser: null};

async function loadSessionWallets() {
  const sel = document.getElementById('session-wallet');
  sel.innerHTML = '<option value="">加载中...</option>';
  const d = await api('wallets_tree');
  if (!d.tree) return;
  sel.innerHTML = '';
  for (const [hash, group] of Object.entries(d.tree)) {
    let idx = 0;
    for (const [wname, addrs] of Object.entries(group.wallets || {})) {
      if (addrs.SUI) {
        const label = (group.mnemonic_nickname || wname) + ' - ' + addrs.SUI.substring(0, 10) + '...';
        const opt = document.createElement('option');
        opt.value = wname;
        opt.dataset.accountIndex = idx;
        opt.textContent = label;
        sel.appendChild(opt);
      }
      idx++;
    }
  }
  if (sel.options.length === 0) {
    sel.innerHTML = '<option value="">没有 Sui 钱包，请先添加</option>';
  }
}

async function doStartSession(mode) {
  const sel = document.getElementById('session-wallet');
  const wallet_name = sel.value;
  if (!wallet_name) return alert('请先选择钱包');
  const account_index = parseInt(sel.options[sel.selectedIndex].dataset.accountIndex) || 0;
  const timeVal = parseInt(document.getElementById(mode + '-time').value) || 0;
  const signsVal = parseInt(document.getElementById(mode + '-signs').value) || 0;
  const d = await api('dapp_connect', {
    wallet_name, account_index,
    max_time_minutes: timeVal,
    max_signs: signsVal,
    mode: mode
  });
  if (d.error) return alert('授权失败: ' + d.error);
  showModeActive(mode, d);
}

async function doRevokeSession(mode) {
  await api('dapp_disconnect', {mode: mode});
  showModeInactive(mode);
}

function showModeActive(mode, d) {
  document.getElementById(mode + '-inactive').style.display = 'none';
  document.getElementById(mode + '-active').style.display = 'block';
  const badge = document.getElementById(mode + '-badge');
  badge.textContent = mode === 'api' ? t('apiBadgeActive') : t('browserBadgeActive');
  badge.style.background = 'rgba(74,222,128,0.2)';
  badge.style.color = '#4ade80';
  document.getElementById(mode + '-addr').textContent = d.address || '?';
  document.getElementById(mode + '-count').textContent = d.signCount || 0;
  document.getElementById(mode + '-limit').textContent = d.maxSigns > 0 ? '/ ' + d.maxSigns : '/ ∞';

  if (sessionTimers[mode]) clearInterval(sessionTimers[mode]);
  if (d.maxTimeSeconds > 0) {
    let remaining = Math.max(0, d.maxTimeSeconds - (d.elapsedSeconds || 0));
    updateModeRemaining(mode, remaining);
    sessionTimers[mode] = setInterval(() => {
      remaining--;
      if (remaining <= 0) { clearInterval(sessionTimers[mode]); checkAllSessions(); }
      updateModeRemaining(mode, remaining);
    }, 1000);
  } else {
    document.getElementById(mode + '-remaining').textContent = '不限时';
    document.getElementById(mode + '-remaining').style.color = '#4ade80';
  }
}

function updateModeRemaining(mode, secs) {
  const el = document.getElementById(mode + '-remaining');
  if (secs <= 0) { el.textContent = '已过期'; el.style.color = '#ef5350'; return; }
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  el.textContent = m + ':' + String(s).padStart(2, '0');
  el.style.color = secs < 120 ? '#ef5350' : '#fbbf24';
}

function showModeInactive(mode) {
  document.getElementById(mode + '-inactive').style.display = 'block';
  document.getElementById(mode + '-active').style.display = 'none';
  const badge = document.getElementById(mode + '-badge');
  badge.textContent = mode === 'api' ? t('apiBadgeInactive') : t('browserBadgeInactive');
  badge.style.background = 'rgba(239,83,80,0.2)';
  badge.style.color = '#ef5350';
  if (sessionTimers[mode]) { clearInterval(sessionTimers[mode]); sessionTimers[mode] = null; }
}

async function checkAllSessions() {
  const d = await api('dapp_status', {});
  if (d.api && d.api.active) showModeActive('api', d.api); else showModeInactive('api');
  if (d.browser && d.browser.active) showModeActive('browser', d.browser); else showModeInactive('browser');
}

// Legacy
function openDappModal() {}
function closeDapp() {}

// ─── Whitelist Management ───
function openWhitelistModal() {
  document.getElementById('wl-overlay').classList.add('active');
  loadWhitelist();
}
function closeWhitelist() { document.getElementById('wl-overlay').classList.remove('active'); }

async function loadWhitelist() {
  const d = await api('whitelist', {});
  renderOrigins(d.origins || []);
  renderContracts(d.contracts || []);
}

function renderOrigins(origins) {
  const el = document.getElementById('wl-origins-list');
  if (!origins.length) { el.innerHTML = '<div style="color:#666;font-size:0.85em;padding:4px">暂无</div>'; return; }
  el.innerHTML = origins.map(o => `<div style="display:flex;align-items:center;gap:8px;padding:5px 8px;background:#1a2a1a;border-radius:4px;margin-bottom:3px;font-size:0.85em">
    <span style="flex:1;color:#ccc;font-family:monospace;word-break:break-all">${esc(o)}</span>
    <button class="btn btn-sm btn-danger" onclick="removeOrigin('${esc(o)}')">✕</button>
  </div>`).join('');
}

function renderContracts(contracts) {
  const el = document.getElementById('wl-contracts-list');
  if (!contracts.length) { el.innerHTML = '<div style="color:#666;font-size:0.85em;padding:4px">暂无（不限制合约）</div>'; return; }
  el.innerHTML = contracts.map(c => `<div style="display:flex;align-items:center;gap:8px;padding:5px 8px;background:#1a1a2a;border-radius:4px;margin-bottom:3px;font-size:0.85em">
    <span style="flex:1;color:#ccc;font-family:monospace;word-break:break-all">${esc(c)}</span>
    <button class="btn btn-sm btn-danger" onclick="removeContract('${esc(c)}')">✕</button>
  </div>`).join('');
}

async function addOrigin() {
  const input = document.getElementById('wl-origin-input');
  let val = input.value.trim();
  if (!val) return;
  // 自动提取 origin（去掉路径），如 https://example.com/path → https://example.com
  try {
    const u = new URL(val);
    val = u.origin;
  } catch(e) {
    // 不是合法 URL（如 chrome-extension://），保持原样
  }
  const d = await api('whitelist/origins/add', { origin: val });
  if (d.ok) { input.value = ''; renderOrigins(d.origins); }
  else alert(d.error || '添加失败');
}

async function removeOrigin(origin) {
  if (!confirm('确定移除 ' + origin + ' ？')) return;
  const d = await api('whitelist/origins/remove', { origin });
  if (d.ok) renderOrigins(d.origins);
  else alert(d.error || '移除失败');
}

async function addContract() {
  const input = document.getElementById('wl-contract-input');
  const val = input.value.trim();
  if (!val) return;
  const d = await api('whitelist/contracts/add', { contract: val });
  if (d.ok) { input.value = ''; renderContracts(d.contracts); }
  else alert(d.error || '添加失败');
}

async function removeContract(contract) {
  if (!confirm('确定移除合约 ' + contract.substring(0, 20) + '... ？')) return;
  const d = await api('whitelist/contracts/remove', { contract });
  if (d.ok) renderContracts(d.contracts);
  else alert(d.error || '移除失败');
}
</script>
</body>
</html>
"""


class WalletHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[HTTP] {args[0]}")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        path = self.path
        result = {"error": "unknown endpoint"}

        if path == "/api/wallets_tree":
            result = {"tree": load_wallets_tree()}

        elif path == "/api/generate":
            if not MNEMONIC_MANAGER_AVAILABLE:
                result = {"error": "助记词管理器不可用"}
            else:
                mnemonic = body.get("mnemonic", "").strip()
                mnemonic_nickname = body.get("mnemonic_nickname", "").strip()
                if not mnemonic or not mnemonic_nickname:
                    result = {"error": "助记词和助记词昵称不能为空"}
                elif not manager.validate_mnemonic(mnemonic):
                    result = {"error": "无效的助记词。请确保 12/15/18/21/24 个 BIP39 单词，空格分隔。"}
                else:
                    try:
                        # 使用助记词昵称作为钱包名称前缀
                        # 生成唯一的钱包名称
                        import time
                        wallet_name = f"{mnemonic_nickname}_{int(time.time())}"
                        
                        wallets = manager.generate_wallet_from_mnemonic(mnemonic, wallet_name)
                        
                        # 保存助记词和昵称到Keychain
                        save_mnemonic_with_nickname(mnemonic, mnemonic_nickname, wallet_name)
                        
                        # 保存钱包地址
                        manager.save_wallet_addresses(wallet_name, wallets)
                        result = {"ok": True, "wallets": wallets}
                    except Exception as e:
                        result = {"error": str(e)}

        elif path == "/api/delete":
            name = body.get("name", "").strip()
            if not name:
                result = {"error": "钱包名称不能为空"}
            else:
                try:
                    delete_wallet(name)
                    result = {"ok": True}
                except Exception as e:
                    result = {"error": str(e)}

        elif path == "/api/delete_mnemonic":
            mnemonic_hash = body.get("mnemonic_hash", "").strip()
            if not mnemonic_hash:
                result = {"error": "助记词哈希不能为空"}
            else:
                try:
                    # 删除助记词及其所有钱包
                    delete_mnemonic(mnemonic_hash)
                    result = {"ok": True}
                except Exception as e:
                    result = {"error": str(e)}

        elif path == "/api/rename_wallet":
            old_name = body.get("old_name", "").strip()
            new_name = body.get("new_name", "").strip()
            
            if not old_name or not new_name:
                result = {"error": "钱包名称不能为空"}
            elif old_name == new_name:
                result = {"error": "新旧名称相同"}
            else:
                try:
                    # 重命名钱包
                    rename_wallet(old_name, new_name)
                    result = {"ok": True}
                except Exception as e:
                    result = {"error": str(e)}

        elif path == "/api/rename_mnemonic":
            mnemonic_hash = body.get("mnemonic_hash", "").strip()
            new_name = body.get("new_name", "").strip()
            
            if not mnemonic_hash or not new_name:
                result = {"error": "助记词哈希和新名称不能为空"}
            else:
                try:
                    # 修改助记词昵称
                    rename_mnemonic(mnemonic_hash, new_name)
                    result = {"ok": True}
                except Exception as e:
                    result = {"error": str(e)}

        elif path == "/api/check_bip44_mode":
            # 检查是否是BIP44模式
            result = {"bip44_mode": BIP44_MODE}

        elif path == "/api/dapp_connect":
            # 启动签名 Session（支持 mode: api / browser）
            try:
                from sui_bridge import bridge, start_bridge_thread
                wallet_name = body.get("wallet_name", "").strip()
                account_index = body.get("account_index", 0)
                max_time_minutes = body.get("max_time_minutes", 0)
                max_signs = body.get("max_signs", 0)
                mode = body.get("mode", "api")
                
                if not wallet_name:
                    result = {"error": "请选择钱包"}
                else:
                    if not hasattr(self, '_bridge_started'):
                        start_bridge_thread()
                        WalletHandler._bridge_started = True
                        import time; time.sleep(1)
                    
                    status = bridge.create_session(
                        wallet_name=wallet_name,
                        account_index=int(account_index),
                        max_time_minutes=int(max_time_minutes),
                        max_signs=int(max_signs),
                        mode=mode
                    )
                    result = {"ok": True, **status}
            except Exception as e:
                result = {"error": str(e)}

        elif path == "/api/dapp_disconnect":
            try:
                from sui_bridge import bridge
                mode = body.get("mode", "api")
                bridge.revoke_session(mode=mode)
                result = {"ok": True}
            except Exception as e:
                result = {"error": str(e)}

        elif path == "/api/dapp_status":
            try:
                from sui_bridge import bridge
                mode = body.get("mode", None)
                if mode:
                    s = bridge._get_active_session(mode)
                    result = s.status() if s else {"active": False}
                else:
                    api_s = bridge.api_session
                    browser_s = bridge.browser_session
                    result = {
                        "api": api_s.status() if api_s else {"active": False},
                        "browser": browser_s.status() if browser_s else {"active": False}
                    }
            except Exception as e:
                result = {"error": str(e)}

        elif path == "/api/whitelist":
            # 获取白名单
            try:
                from sui_bridge import load_whitelist
                result = load_whitelist()
            except Exception as e:
                result = {"error": str(e)}

        elif path == "/api/whitelist/origins/add":
            try:
                from sui_bridge import load_whitelist, save_whitelist
                origin_val = body.get("origin", "").strip()
                if not origin_val:
                    result = {"error": "origin 不能为空"}
                else:
                    wl = load_whitelist()
                    if origin_val not in wl["origins"]:
                        wl["origins"].append(origin_val)
                        save_whitelist(wl)
                    result = {"ok": True, "origins": wl["origins"]}
            except Exception as e:
                result = {"error": str(e)}

        elif path == "/api/whitelist/origins/remove":
            try:
                from sui_bridge import load_whitelist, save_whitelist
                origin_val = body.get("origin", "").strip()
                if not origin_val:
                    result = {"error": "origin 不能为空"}
                else:
                    wl = load_whitelist()
                    if origin_val in wl["origins"]:
                        wl["origins"].remove(origin_val)
                        save_whitelist(wl)
                    result = {"ok": True, "origins": wl["origins"]}
            except Exception as e:
                result = {"error": str(e)}

        elif path == "/api/whitelist/contracts/add":
            try:
                from sui_bridge import load_whitelist, save_whitelist
                contract = body.get("contract", "").strip()
                if not contract:
                    result = {"error": "合约地址不能为空"}
                else:
                    wl = load_whitelist()
                    if contract not in wl["contracts"]:
                        wl["contracts"].append(contract)
                        save_whitelist(wl)
                    result = {"ok": True, "contracts": wl["contracts"]}
            except Exception as e:
                result = {"error": str(e)}

        elif path == "/api/whitelist/contracts/remove":
            try:
                from sui_bridge import load_whitelist, save_whitelist
                contract = body.get("contract", "").strip()
                if not contract:
                    result = {"error": "合约地址不能为空"}
                else:
                    wl = load_whitelist()
                    if contract in wl["contracts"]:
                        wl["contracts"].remove(contract)
                        save_whitelist(wl)
                    result = {"ok": True, "contracts": wl["contracts"]}
            except Exception as e:
                result = {"error": str(e)}
        
        elif path == "/api/balances":
            address = body.get("address", "").strip()
            if not address:
                result = {"error": "address required"}
            else:
                balances = fetch_sui_balances(address)
                result = {"ok": True, "balances": balances}

        elif path == "/api/reset_keychain_auth":
            try:
                import keyring
                import subprocess
                service_name = "openclaw_bot"
                raw = load_wallets_raw()
                chain_suffixes = ["_sui", "_solana", "_ethereum", "_evm"]
                wallet_names = set()
                for key in raw:
                    wn = key
                    for suffix in chain_suffixes:
                        if key.endswith(suffix):
                            wn = key[:-len(suffix)]
                            break
                    wallet_names.add(wn)
                
                # 先读出所有数据
                saved_data = {}
                for wn in wallet_names:
                    for prefix in ["mnemonic_", "nickname_"]:
                        try:
                            val = keyring.get_password(service_name, f"{prefix}{wn}")
                            if val:
                                saved_data[f"{prefix}{wn}"] = val
                        except Exception:
                            pass
                
                # 删除所有条目
                deleted_count = 0
                for key in saved_data:
                    try:
                        keyring.delete_password(service_name, key)
                        deleted_count += 1
                    except Exception:
                        pass
                
                # 用 security 命令写回（不带 -A，不自动授权）
                # 下次 Python keyring 读取时会弹 macOS 授权弹窗
                for key, val in saved_data.items():
                    try:
                        subprocess.run([
                            "security", "add-generic-password",
                            "-s", service_name,
                            "-a", key,
                            "-w", val,
                            "-U",  # 如果已存在则更新
                            "login.keychain"
                        ], check=True, capture_output=True)
                    except Exception as e:
                        print(f"security add-generic-password failed for {key}: {e}")
                
                result = {"ok": True, "deleted": deleted_count}
            except Exception as e:
                result = {"error": str(e)}

        elif path == "/api/generate_from_mnemonic":
            if not MNEMONIC_MANAGER_AVAILABLE:
                result = {"error": "助记词管理器不可用"}
            else:
                mnemonic_hash = body.get("mnemonic_hash", "").strip()
                wallet_name = body.get("wallet_name", "").strip()
                account_index = body.get("account_index", 0)
                address_index = body.get("address_index", None)
                
                if not mnemonic_hash:
                    result = {"error": "助记词哈希不能为空"}
                else:
                    try:
                        # 从助记词哈希找到对应的助记词
                        mnemonic = get_mnemonic_by_hash(mnemonic_hash)
                        if not mnemonic:
                            result = {"error": "找不到对应的助记词"}
                        else:
                            # BIP44模式：自动计算下一个索引
                            if BIP44_MODE and address_index is None:
                                # 获取该助记词分组下的所有钱包
                                tree = load_wallets_tree()
                                if mnemonic_hash in tree:
                                    existing_wallets = list(tree[mnemonic_hash]["wallets"].keys())
                                else:
                                    existing_wallets = []
                                
                                # 自动生成下一个钱包（BIP44自动递增）
                                wallets, auto_wallet_name = manager.generate_next_wallet(mnemonic, existing_wallets)
                                wallet_name = auto_wallet_name  # 使用自动生成的钱包名称
                            else:
                                # 使用指定的钱包名称和索引
                                if not wallet_name and not BIP44_MODE:
                                    result = {"error": "钱包名称不能为空"}
                                    self.send_response(200)
                                    self.send_header("Content-Type", "application/json; charset=utf-8")
                                    self.end_headers()
                                    self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
                                    return
                                
                                # 生成新钱包
                                if BIP44_MODE:
                                    # BIP44模式：如果钱包名称为空，自动生成一个
                                    if not wallet_name:
                                        # 获取该助记词分组下的所有钱包
                                        tree = load_wallets_tree()
                                        if mnemonic_hash in tree:
                                            existing_wallets = list(tree[mnemonic_hash]["wallets"].keys())
                                        else:
                                            existing_wallets = []
                                        
                                        # 自动生成下一个钱包（BIP44自动递增）
                                        wallets, auto_wallet_name = manager.generate_next_wallet(mnemonic, existing_wallets)
                                        wallet_name = auto_wallet_name  # 使用自动生成的钱包名称
                                    else:
                                        wallets = manager.generate_wallet_from_mnemonic(
                                            mnemonic, wallet_name, 
                                            account_index=int(account_index), 
                                            address_index=int(address_index) if address_index is not None else 0
                                        )
                                else:
                                    wallets = manager.generate_wallet_from_mnemonic(mnemonic, wallet_name)
                            
                            # 保存钱包地址
                            manager.save_wallet_addresses(wallet_name, wallets)
                            
                            # 保存助记词和昵称到Keychain
                            nickname = None
                            raw = load_wallets_raw()
                            chain_suffixes = ["_sui", "_solana", "_ethereum"]
                            existing_wallet_names = set()
                            
                            for key in raw:
                                w_name = key
                                for suffix in chain_suffixes:
                                    if key.endswith(suffix):
                                        w_name = key[: -len(suffix)]
                                        break
                                existing_wallet_names.add(w_name)
                            
                            # 从相同助记词的其他钱包中获取昵称
                            for w_name in existing_wallet_names:
                                w_mnemonic = get_mnemonic_from_keychain(w_name)
                                if w_mnemonic:
                                    w_hash = hashlib.sha256(w_mnemonic.encode()).hexdigest()[:16]
                                    if w_hash == mnemonic_hash:
                                        w_nickname = get_mnemonic_nickname_from_keychain(w_name)
                                        if w_nickname:
                                            nickname = w_nickname
                                            break
                            
                            if not nickname:
                                nickname = f"助记词_{mnemonic_hash[:8]}"
                            
                            save_mnemonic_with_nickname(mnemonic, nickname, wallet_name)
                            
                            result = {"ok": True, "wallets": wallets, "wallet_name": wallet_name, "bip44_mode": BIP44_MODE}
                    except Exception as e:
                        result = {"error": str(e)}

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    port = find_free_port()
    try:
        server = http.server.HTTPServer(("127.0.0.1", port), WalletHandler)
    except OSError:
        # 端口冲突时重试
        port = find_free_port()
        server = http.server.HTTPServer(("127.0.0.1", port), WalletHandler)

    url = f"http://127.0.0.1:{port}"
    print(f"🚀 MiaoWallet Pro v2 (树状图)", flush=True)
    print(f"📍 {url}", flush=True)
    print(f"⏹  Ctrl+C 退出", flush=True)

    def open_browser():
        import time, subprocess
        time.sleep(1)
        # 强制用 Chrome 打开
        try:
            subprocess.Popen(['open', '-a', 'Google Chrome', url])
        except Exception:
            webbrowser.open(url)

    t = threading.Thread(target=open_browser, daemon=True)
    t.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已关闭")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from mnemonic_manager_bip44 import MnemonicManagerBIP44 as MnemonicManager
    MNEMONIC_MANAGER_AVAILABLE = True
    BIP44_MODE = True
    print("✅ 使用BIP44标准模式")
except ImportError as e:
    print(f"⚠️  无法导入BIP44助记词管理器: {e}")
    try:
        from mnemonic_manager import MnemonicManager
        MNEMONIC_MANAGER_AVAILABLE = True
        BIP44_MODE = False
        print("⚠️  使用旧版模式 (非BIP44标准)")
    except ImportError as e2:
        print(f"❌  无法导入任何助记词管理器: {e2}")
        MNEMONIC_MANAGER_AVAILABLE = False
        BIP44_MODE = False

if '__file__' in globals():
    WALLET_DIR = os.path.dirname(os.path.abspath(__file__))
else:
    WALLET_DIR = os.getcwd()
WALLET_FILE = os.path.join(WALLET_DIR, ".wallet_addresses.json")

manager = MnemonicManager() if MNEMONIC_MANAGER_AVAILABLE else None


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

.header { background: var(--bg2); padding: 18px; text-align: center; }
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
</style>
</head>
<body>

<div class="header"><h1>🔐 MiaoWallet Pro</h1></div>
<div class="status-bar" id="status">就绪</div>

<div class="container">
  <div class="left">
    <div class="panel">
      <h2>📋 钱包列表</h2>
      <div id="wallet-tree"><div class="tree-empty">加载中...</div></div>
    </div>
  </div>
  <div class="right">
    <div class="panel">
      <h2>🚀 功能</h2>
      <button class="btn btn-red" onclick="openAddModal()">➕ 新助记词</button>
      <button class="btn btn-blue" onclick="refreshTree()">🔄 刷新</button>
    </div>
    <div class="info">
      <strong>📖 使用说明</strong><br><br>
      1. 点击「新助记词」添加钱包<br>
      2. 输入 BIP39 助记词（12/24词）<br>
      3. 自动生成 SUI / Solana / Ethereum 地址<br>
      4. 助记词安全存储到 macOS Keychain<br><br>
      点击钱包名展开/折叠地址<br>
      点击 📋 复制地址
    </div>
  </div>
</div>

<!-- Add Modal -->
<div class="overlay" id="add-overlay">
  <div class="modal">
    <h2>🔐 添加新助记词钱包</h2>
    <div id="add-form">
      <div class="field">
        <label>步骤1: 输入助记词（BIP39，空格分隔）</label>
        <textarea id="inp-mnemonic" placeholder="abandon abandon abandon ..."></textarea>
        <button class="example-btn" onclick="document.getElementById('inp-mnemonic').value='abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about'">填入测试助记词</button>
      </div>
      <div class="field">
        <label>步骤2: 助记词昵称</label>
        <input type="text" id="inp-name" value="我的助记词" placeholder="给这个助记词起个名字">
      </div>
      <div class="modal-btns">
        <button class="btn btn-red" onclick="doGenerate()">🚀 生成钱包</button>
        <button class="btn" style="background:#666" onclick="closeAdd()">取消</button>
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
    <p style="font-size:0.82em;color:var(--muted)">此操作将同时删除 Keychain 中的助记词</p>
    <div class="modal-btns">
      <button class="btn btn-danger" onclick="doDelete()">删除</button>
      <button class="btn" style="background:#666" onclick="closeDel()">取消</button>
    </div>
  </div>
</div>

<script>
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
    document.getElementById('status').textContent = '✅ 地址已复制';
    setTimeout(() => document.getElementById('status').textContent = '就绪', 2000);
  });
}

function renderTree(data) {
  walletData = data;
  const container = document.getElementById('wallet-tree');
  const mnemonicHashes = Object.keys(data);

  if (mnemonicHashes.length === 0) {
    container.innerHTML = '<div class="tree-empty">暂无钱包，点击「新助记词」添加</div>';
    document.getElementById('status').textContent = '暂无钱包';
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
        <span class="count">${walletNames.length} 钱包</span>
        <button class="btn btn-sm btn-green" onclick="event.stopPropagation(); generateNewWalletFromMnemonic('${esc(mnemonicHash)}', '${esc(mnemonicPreview)}')" title="生成新钱包">➕</button>
        <button class="btn btn-sm btn-warning" onclick="event.stopPropagation(); renameMnemonic('${esc(mnemonicHash)}', '${esc(mnemonicPreview)}')" title="修改昵称">✏️</button>
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
          <span class="count">${chainKeys.length} 链</span>
          <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); renameWallet('${esc(walletName)}')" title="改名">✏️</button>
          <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); confirmDelete('${esc(walletName)}')">🗑</button>
        </div>
        <div class="wallet-children">`;
      for (const chain of chainKeys) {
        const addr = chains[chain];
        html += `<div class="chain-row">
          <span class="chain-tag ${chainClass(chain)}">${esc(chain)}</span>
          <span class="chain-addr">${esc(addr)}</span>
          <span class="chain-copy" onclick="copyAddr('${esc(addr)}')" title="复制">📋</span>
        </div>`;
      }
      html += '</div></div>';
    }
    html += '</div></div>';
  }
  
  container.innerHTML = html;
  document.getElementById('status').textContent = `已加载 ${mnemonicHashes.length} 个助记词，${totalWallets} 个钱包`;
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
  if (!mnemonic) { alert('请输入助记词'); return; }
  if (!mnemonicNickname) { alert('请输入助记词昵称'); return; }

  document.getElementById('add-form').style.display = 'none';
  const res = document.getElementById('add-result');
  res.style.display = '';
  res.innerHTML = '<div class="msg msg-ok">⏳ 正在生成...</div>';

  const data = await api('generate', { mnemonic, mnemonic_nickname: mnemonicNickname });
  if (data.error) {
    res.innerHTML = `<div class="msg msg-err">❌ ${esc(data.error)}</div>
      <div class="modal-btns"><button class="btn" style="background:#666" onclick="openAddModal()">重试</button>
      <button class="btn" style="background:#444" onclick="closeAdd()">关闭</button></div>`;
    return;
  }

  let lines = '';
  for (const [c, a] of Object.entries(data.wallets)) {
    lines += `<div class="addr-line"><span class="r-chain">${esc(c)}:</span> <span class="r-addr">${esc(a)}</span></div>`;
  }
  res.innerHTML = `<div class="msg msg-ok">✅ 助记词「${esc(mnemonicNickname)}」生成成功！</div>
    <div class="result-box">${lines}</div>
    <div class="modal-btns" style="margin-top:14px">
      <button class="btn btn-green" onclick="closeAdd(); refreshTree();">完成</button></div>`;
}

// Delete
let pendingDelete = null;
let pendingDeleteMnemonic = null;

function confirmDelete(name) {
  pendingDelete = name;
  pendingDeleteMnemonic = null;
  document.getElementById('del-name').textContent = name;
  document.getElementById('del-title').textContent = '⚠️ 确认删除钱包';
  document.getElementById('del-desc').textContent = `确定要删除钱包「${name}」及其所有链地址吗？`;
  document.getElementById('del-overlay').classList.add('active');
}

function confirmDeleteMnemonic(mnemonicHash, mnemonicPreview) {
  pendingDelete = null;
  pendingDeleteMnemonic = {hash: mnemonicHash, preview: mnemonicPreview};
  document.getElementById('del-name').textContent = mnemonicPreview;
  document.getElementById('del-title').textContent = '⚠️ 确认删除助记词';
  document.getElementById('del-desc').textContent = `确定要删除助记词「${mnemonicPreview}」及其所有钱包吗？此操作不可恢复！`;
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
    document.getElementById('status').textContent = `已改名: ${oldName} → ${newName}`;
    refreshTree();
  } else {
    alert('改名失败: ' + (data.error || '未知错误'));
  }
}

// 修改助记词昵称功能
function renameMnemonic(mnemonicHash, currentName) {
  const newName = prompt(`请输入新的助记词昵称 (当前: ${currentName}):`, currentName);
  
  if (newName && newName !== currentName && newName.trim() !== '') {
    const trimmedName = newName.trim();
    if (confirm(`确定要将助记词昵称 "${currentName}" 改为 "${trimmedName}" 吗？`)) {
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
    document.getElementById('status').textContent = `已修改助记词昵称: ${newName}`;
    refreshTree();
  } else {
    alert('修改失败: ' + (data.error || '未知错误'));
  }
}

async function doDelete() {
  if (pendingDelete) {
    // 删除钱包
    const data = await api('delete', { name: pendingDelete });
    closeDel();
    if (data.ok) {
      document.getElementById('status').textContent = `已删除钱包: ${pendingDelete}`;
    } else {
      alert('删除失败: ' + (data.error || '未知错误'));
    }
  } else if (pendingDeleteMnemonic) {
    // 删除助记词
    const data = await api('delete_mnemonic', { 
      mnemonic_hash: pendingDeleteMnemonic.hash,
      mnemonic_preview: pendingDeleteMnemonic.preview
    });
    closeDel();
    if (data.ok) {
      document.getElementById('status').textContent = `已删除助记词: ${pendingDeleteMnemonic.preview}`;
    } else {
      alert('删除失败: ' + (data.error || '未知错误'));
    }
  }
  refreshTree();
}

// Init
refreshTree();
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
        import time
        time.sleep(1)
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

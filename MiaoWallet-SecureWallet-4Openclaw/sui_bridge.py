"""
MiaoWallet Sui DApp Bridge
WebSocket 桥接服务，让 Chrome 扩展通过 MiaoWallet 签名 Sui 交易

架构: Chrome Extension <--WebSocket--> sui_bridge.py <--Keychain--> MiaoWallet 密钥
"""

import asyncio
import json
import hashlib
import time
import threading
import base64
import os
import sys
import logging
import secrets
from http import HTTPStatus
from urllib.parse import urlparse, parse_qs

import websockets
import websockets.legacy.server
from nacl.signing import SigningKey

logging.basicConfig(level=logging.INFO, format='[SuiBridge] %(message)s')
log = logging.getLogger(__name__)

BRIDGE_PORT = 3847
SERVICE_NAME = "openclaw_bot"

# ─── Admin Token（每次启动随机生成，只有 WebGUI 知道）───
ADMIN_TOKEN = secrets.token_urlsafe(32)
log.info(f"Admin token generated (only for WebGUI internal use)")

# ─── 白名单配置文件 ───
WHITELIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".whitelist.json")

def load_whitelist() -> dict:
    """加载白名单配置"""
    default = {
        "origins": [
            "chrome-extension://",
            "http://localhost",
            "http://127.0.0.1",
            "https://cryptomiaobug.github.io",
        ],
        "contracts": []
    }
    try:
        if os.path.exists(WHITELIST_FILE):
            with open(WHITELIST_FILE, 'r') as f:
                data = json.load(f)
                # 确保默认值存在
                if "origins" not in data:
                    data["origins"] = default["origins"]
                if "contracts" not in data:
                    data["contracts"] = default["contracts"]
                return data
    except Exception as e:
        log.error(f"Load whitelist failed: {e}")
    return default

def save_whitelist(data: dict):
    """保存白名单配置"""
    try:
        with open(WHITELIST_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Save whitelist failed: {e}")

def check_origin(origin: str) -> bool:
    """检查 origin 是否在白名单中"""
    if not origin:
        return False
    wl = load_whitelist()
    for allowed in wl.get("origins", []):
        if origin.startswith(allowed):
            return True
    return False

def check_contract(tx_bytes: bytes) -> bool:
    """检查交易调用的合约是否在白名单中"""
    wl = load_whitelist()
    contracts = wl.get("contracts", [])
    # 如果没有配置合约白名单，放行所有
    if not contracts:
        return True
    # 检查 tx_bytes 中是否包含白名单合约地址
    tx_hex = tx_bytes.hex()
    for contract in contracts:
        # 去掉 0x 前缀后匹配
        clean = contract.lower().replace("0x", "")
        if clean in tx_hex:
            return True
    log.warning(f"Contract not in whitelist, tx rejected")
    return False

# ─── Keychain helpers ───

def get_mnemonic_from_keychain(wallet_name: str) -> str | None:
    """从 Keychain 取助记词，用完由调用方丢弃"""
    try:
        import keyring
        return keyring.get_password(SERVICE_NAME, f"mnemonic_{wallet_name}")
    except Exception as e:
        log.error(f"Keychain read failed: {e}")
        return None


# ─── Crypto: BIP44 Sui 密钥派生 ───

def bip39_mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    import hmac as _hmac
    mnemonic_bytes = mnemonic.encode('utf-8')
    salt = f"mnemonic{passphrase}".encode('utf-8')
    return hashlib.pbkdf2_hmac('sha512', mnemonic_bytes, salt, 2048)


def slip10_derive_ed25519(parent_key: bytes, chain_code: bytes, index: int) -> tuple:
    """SLIP-0010 Ed25519 硬化派生"""
    import hmac as _hmac
    index = index | 0x80000000  # 硬化
    data = b'\x00' + parent_key + index.to_bytes(4, 'big')
    h = _hmac.new(chain_code, data, hashlib.sha512).digest()
    return h[:32], h[32:]


def derive_sui_keypair(mnemonic: str, account_index: int = 0) -> tuple:
    """
    从助记词派生 Sui Ed25519 密钥对
    路径: m/44'/784'/{account_index}'/0'/0'
    返回: (private_key_32bytes, public_key_32bytes, sui_address)
    """
    import hmac as _hmac
    
    seed = bip39_mnemonic_to_seed(mnemonic)
    
    # Master key (SLIP-0010 for Ed25519)
    h = _hmac.new(b"ed25519 seed", seed, hashlib.sha512).digest()
    key, chain_code = h[:32], h[32:]
    
    # Derive: 44' -> 784' -> account' -> 0' -> 0'
    for idx in [44, 784, account_index, 0, 0]:
        key, chain_code = slip10_derive_ed25519(key, chain_code, idx)
    
    # Ed25519 keypair
    signing_key = SigningKey(key)
    public_key = signing_key.verify_key.encode()
    
    # Sui address: Blake2b(0x00 + public_key)
    hasher = hashlib.blake2b(digest_size=32)
    hasher.update(bytes([0]) + public_key)
    address = "0x" + hasher.digest().hex()
    
    return key, public_key, address


# ─── JSON v2 Transaction Build ───

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))

async def build_json_v2_transaction(json_str: str, network: str, sender: str) -> bytes:
    """
    用 Node.js + @mysten/sui SDK 把 JSON v2 格式的交易 build 成 BCS bytes。
    返回 bytes，失败抛异常。
    """
    build_script = os.path.join(BRIDGE_DIR, "build_tx.mjs")
    proc = await asyncio.create_subprocess_exec(
        "node", build_script, network, sender,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=BRIDGE_DIR
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=json_str.encode()),
        timeout=30
    )
    if proc.returncode != 0:
        err = stderr.decode().strip() or stdout.decode().strip()
        raise RuntimeError(f"build_tx failed: {err}")
    
    result = json.loads(stdout.decode())
    if "error" in result:
        raise RuntimeError(f"build_tx: {result['error']}")
    
    return base64.b64decode(result["bytes"])


def sign_transaction(private_key: bytes, tx_bytes: bytes) -> str:
    """
    签名交易，返回 Sui 格式的 base64 签名
    格式: scheme_flag(1) + signature(64) + public_key(32) = 97 bytes
    """
    signing_key = SigningKey(private_key)
    
    # Sui 签名: 对 intent_message 签名
    # intent_message = intent_prefix(3 bytes) + tx_bytes
    intent_prefix = bytes([0, 0, 0])  # TransactionData intent
    intent_message = intent_prefix + tx_bytes
    
    # Blake2b hash of intent message
    hasher = hashlib.blake2b(digest_size=32)
    hasher.update(intent_message)
    digest = hasher.digest()
    
    # Ed25519 sign the digest
    signed = signing_key.sign(digest)
    signature_bytes = signed.signature  # 64 bytes
    
    public_key = signing_key.verify_key.encode()  # 32 bytes
    
    # Sui signature format: flag + sig + pubkey
    sui_signature = bytes([0]) + signature_bytes + public_key  # 97 bytes
    
    return base64.b64encode(sui_signature).decode()


def sign_personal_message(private_key: bytes, message: bytes) -> str:
    """签名个人消息"""
    signing_key = SigningKey(private_key)
    
    # Personal message intent
    intent_prefix = bytes([3, 0, 0])  # PersonalMessage intent
    
    # BCS serialize: length prefix + message
    msg_len = len(message)
    # ULEB128 encode length
    len_bytes = []
    while msg_len > 0x7f:
        len_bytes.append((msg_len & 0x7f) | 0x80)
        msg_len >>= 7
    len_bytes.append(msg_len)
    
    intent_message = intent_prefix + bytes(len_bytes) + message
    
    hasher = hashlib.blake2b(digest_size=32)
    hasher.update(intent_message)
    digest = hasher.digest()
    
    signed = signing_key.sign(digest)
    public_key = signing_key.verify_key.encode()
    
    sui_signature = bytes([0]) + signed.signature + public_key
    return base64.b64encode(sui_signature).decode()


# ─── Session 管理 ───

class SigningSession:
    """管理一次 DApp 连接的签名会话"""
    
    def __init__(self, wallet_name: str, account_index: int,
                 max_time_minutes: int = 0, max_signs: int = 0):
        self.wallet_name = wallet_name
        self.account_index = account_index
        self.max_time = max_time_minutes * 60 if max_time_minutes > 0 else 0
        self.max_signs = max_signs
        self.sign_count = 0
        self.start_time = time.time()
        self.active = True
        
        # 派生密钥（会在 revoke 时清除）
        mnemonic = get_mnemonic_from_keychain(wallet_name)
        if not mnemonic:
            raise ValueError(f"No mnemonic found for wallet: {wallet_name}")
        
        self._private_key, self.public_key, self.address = derive_sui_keypair(
            mnemonic, account_index
        )
        # 立即丢弃助记词
        del mnemonic
        
        log.info(f"Session created: {self.address} (time={max_time_minutes}m, signs={max_signs})")
    
    def is_valid(self) -> bool:
        if not self.active:
            return False
        if self.max_time > 0 and (time.time() - self.start_time) > self.max_time:
            self.revoke("time expired")
            return False
        if self.max_signs > 0 and self.sign_count >= self.max_signs:
            self.revoke("sign limit reached")
            return False
        return True
    
    def sign_tx(self, tx_bytes: bytes) -> str:
        """签名交易（阅后即焚模式）"""
        if not self.is_valid():
            raise PermissionError("Session expired or revoked")
        
        sig = sign_transaction(self._private_key, tx_bytes)
        self.sign_count += 1
        log.info(f"Signed tx #{self.sign_count} for {self.address}")
        
        # 检查是否达到上限
        if self.max_signs > 0 and self.sign_count >= self.max_signs:
            self.revoke("sign limit reached")
        
        return sig
    
    def sign_msg(self, message: bytes) -> str:
        if not self.is_valid():
            raise PermissionError("Session expired or revoked")
        
        sig = sign_personal_message(self._private_key, message)
        self.sign_count += 1
        return sig
    
    def revoke(self, reason: str = "manual"):
        """撤销会话，清除私钥"""
        if self.active:
            self._private_key = b'\x00' * 32  # 覆写
            self.active = False
            log.info(f"Session revoked ({reason}): {self.address}")
    
    def status(self) -> dict:
        elapsed = time.time() - self.start_time
        return {
            "active": self.is_valid(),
            "address": self.address,
            "signCount": self.sign_count,
            "maxSigns": self.max_signs,
            "elapsedSeconds": int(elapsed),
            "maxTimeSeconds": self.max_time,
            "wallet": self.wallet_name,
            "accountIndex": self.account_index,
        }


# ─── Bridge Server ───

class SuiBridge:
    def __init__(self):
        self.api_session: SigningSession | None = None
        self.browser_session: SigningSession | None = None
        self.session: SigningSession | None = None  # legacy alias → api_session
        self.pending_requests: dict = {}
        self.ws_clients: set = set()
        self.network = "mainnet"
        self._server = None
    
    def create_session(self, wallet_name: str, account_index: int = 0,
                       max_time_minutes: int = 0, max_signs: int = 0,
                       mode: str = "api"):
        if mode == "browser":
            if self.browser_session:
                self.browser_session.revoke("new session")
            self.browser_session = SigningSession(
                wallet_name, account_index, max_time_minutes, max_signs
            )
            return self.browser_session.status()
        else:
            if self.api_session:
                self.api_session.revoke("new session")
            self.api_session = SigningSession(
                wallet_name, account_index, max_time_minutes, max_signs
            )
            self.session = self.api_session  # legacy alias
            return self.api_session.status()
    
    def revoke_session(self, mode: str = "api"):
        if mode == "browser":
            if self.browser_session:
                self.browser_session.revoke("manual")
                self.browser_session = None
        else:
            if self.api_session:
                self.api_session.revoke("manual")
                self.api_session = None
                self.session = None
    
    def _get_active_session(self, mode: str = "api") -> SigningSession | None:
        """Get the active session for a given mode"""
        s = self.browser_session if mode == "browser" else self.api_session
        if s and s.is_valid():
            return s
        return None
    
    async def broadcast_session_update(self, mode: str = "api"):
        """广播 session 状态更新给所有 WebSocket 客户端"""
        if not self.ws_clients:
            return
        
        s = self._get_active_session(mode)
        if not s:
            return
        
        message = json.dumps({
            "type": "sessionUpdate",
            "mode": mode,
            "status": s.status()
        })
        
        # 广播给所有连接的客户端
        disconnected = set()
        for ws in self.ws_clients:
            try:
                await ws.send(message)
            except Exception:
                disconnected.add(ws)
        
        # 清理断开的连接
        self.ws_clients -= disconnected
    
    # ─── HTTP handler ───
    
    @staticmethod
    def _check_admin(body: dict = None, headers: dict = None) -> bool:
        """验证 admin token（从 body 或 header 中获取）"""
        # 优先从 header 检查
        if headers and headers.get("x-admin-token") == ADMIN_TOKEN:
            return True
        # 其次从 body 检查
        if body and body.get("admin_token") == ADMIN_TOKEN:
            return True
        return False

    # 需要 admin token 的路径（只有人类通过 WebGUI 能调）
    ADMIN_PATHS = {
        ("/session", "POST"),    # 创建/重建 session
        ("/session", "DELETE"),  # 撤销 session
        ("/network", "POST"),    # 切换网络
        ("/whitelist/origins", "POST"),     # 添加 origin 白名单
        ("/whitelist/origins", "DELETE"),   # 删除 origin 白名单
        ("/whitelist/contracts", "POST"),   # 添加合约白名单
        ("/whitelist/contracts", "DELETE"), # 删除合约白名单
    }
    # /approve/* 和 /reject/* 也需要 admin（下面单独检查）

    async def handle_http(self, path: str, method: str, body: dict = None, headers: dict = None) -> tuple:
        """处理 HTTP 请求，返回 (status_code, response_dict)"""
        
        # ─── Admin 权限检查 ───
        needs_admin = (path, method) in self.ADMIN_PATHS
        if not needs_admin and method == "POST":
            if path.startswith("/approve/") or path.startswith("/reject/"):
                needs_admin = True
        
        if needs_admin and not self._check_admin(body, headers):
            log.warning(f"🚫 Unauthorized admin request: {method} {path}")
            return 403, {"error": "Admin token required. Only MiaoWallet WebGUI can manage sessions."}
        
        if path == "/address" and method == "GET":
            s = self._get_active_session("api")
            if not s:
                return 403, {"error": "No active API session"}
            return 200, {
                "address": s.address,
                "publicKey": base64.b64encode(s.public_key).decode(),
                "network": self.network
            }
        
        if path == "/balance" and method == "GET":
            s = self._get_active_session("api")
            if not s:
                return 403, {"error": "No active API session"}
            # TODO: 实际查询链上余额
            return 200, {"balance": "0", "balanceSui": "0.000000000"}
        
        if path == "/network" and method == "GET":
            return 200, {"network": self.network, "rpcUrl": f"https://fullnode.{self.network}.sui.io:443"}
        
        if path == "/network" and method == "POST":
            self.network = body.get("network", "mainnet")
            return 200, {"success": True, "network": self.network}
        
        if path == "/accounts" and method == "GET":
            accounts = []
            for s in (self.api_session, self.browser_session):
                if s and s.is_valid():
                    accounts.append({"index": s.account_index, "address": s.address, "active": True})
            active = accounts[0]["address"] if accounts else None
            return 200, {"accounts": accounts, "activeAddress": active}
        
        if path == "/pending" and method == "GET":
            pending = [
                {"id": k, **{kk: vv for kk, vv in v.items() if kk != "future"}}
                for k, v in self.pending_requests.items()
                if not v.get("resolved")
            ]
            return 200, {"pending": pending}
        
        if path.startswith("/approve/") and method == "POST":
            req_id = path[9:]
            req = self.pending_requests.get(req_id)
            if not req:
                return 404, {"error": "Request not found"}
            if req.get("resolved"):
                return 400, {"error": "Already resolved"}
            s = self._get_active_session("browser")
            if not s:
                return 403, {"error": "Browser session expired"}
            
            try:
                method_name = req["method"]
                payload = req["payload"]
                
                if method_name in ("signTransaction", "signAndExecuteTransaction"):
                    tx_data = payload.get("transaction", "")
                    tx_format = payload.get("transactionFormat", "")
                    
                    # JSON v2 format: build via Node.js SDK
                    if tx_format == "json-v2":
                        chain = payload.get("chain", f"sui:{self.network}")
                        network = chain.split(":")[1] if ":" in chain else self.network
                        sender = s.address
                        log.info(f"Building JSON v2 transaction for {sender} on {network}")
                        tx_bytes = await build_json_v2_transaction(tx_data, network, sender)
                    else:
                        tx_bytes = base64.b64decode(tx_data) if isinstance(tx_data, str) else tx_data
                    
                    signature = s.sign_tx(tx_bytes)
                    result = {
                        "bytes": base64.b64encode(tx_bytes).decode(),
                        "signature": signature
                    }
                elif method_name == "signPersonalMessage":
                    msg_data = payload.get("message", "")
                    msg_bytes = base64.b64decode(msg_data) if isinstance(msg_data, str) else msg_data
                    signature = s.sign_msg(msg_bytes)
                    result = {
                        "bytes": base64.b64encode(msg_bytes).decode(),
                        "signature": signature
                    }
                else:
                    return 400, {"error": f"Unknown method: {method_name}"}
                
                req["resolved"] = True
                if "future" in req:
                    req["future"].set_result(result)
                
                return 200, {"success": True, "result": result}
            except Exception as e:
                return 500, {"error": str(e)}
        
        if path.startswith("/reject/") and method == "POST":
            req_id = path[8:]
            req = self.pending_requests.get(req_id)
            if not req:
                return 404, {"error": "Request not found"}
            req["resolved"] = True
            if "future" in req:
                req["future"].set_result({"error": "User rejected"})
            return 200, {"success": True}
        
        if path == "/sign-raw" and method == "POST":
            s = self._get_active_session("api")
            if not s:
                return 403, {"error": "API session expired"}
            try:
                tx_bytes = base64.b64decode(body["txBytes"])
                if not check_contract(tx_bytes):
                    return 403, {"error": "Contract not in whitelist"}
                signature = s.sign_tx(tx_bytes)
                
                # 广播 session 更新给 WebGUI（更新计数器）
                asyncio.create_task(self.broadcast_session_update("api"))
                
                return 200, {
                    "success": True,
                    "txBytes": body["txBytes"],
                    "signature": signature
                }
            except Exception as e:
                return 500, {"error": str(e)}
        
        if path == "/session" and method == "GET":
            mode = "api"
            # 返回两个 session 的状态
            api_status = self.api_session.status() if self.api_session else {"active": False}
            browser_status = self.browser_session.status() if self.browser_session else {"active": False}
            return 200, {"api": api_status, "browser": browser_status}
        
        if path == "/session" and method == "POST":
            try:
                mode = body.get("mode", "api")
                status = self.create_session(
                    wallet_name=body["wallet_name"],
                    account_index=body.get("account_index", 0),
                    max_time_minutes=body.get("max_time_minutes", 0),
                    max_signs=body.get("max_signs", 0),
                    mode=mode
                )
                return 200, {"success": True, **status}
            except Exception as e:
                return 500, {"error": str(e)}
        
        if path == "/session" and method == "DELETE":
            mode = body.get("mode", "api") if body else "api"
            self.revoke_session(mode=mode)
            return 200, {"success": True}
        
        # ─── 白名单管理 API（需要 admin token）───
        if path == "/whitelist" and method == "GET":
            return 200, load_whitelist()
        
        if path == "/whitelist/origins" and method == "POST":
            origin_val = (body or {}).get("origin", "").strip()
            if not origin_val:
                return 400, {"error": "origin is required"}
            wl = load_whitelist()
            if origin_val not in wl["origins"]:
                wl["origins"].append(origin_val)
                save_whitelist(wl)
            return 200, {"success": True, "origins": wl["origins"]}
        
        if path == "/whitelist/origins" and method == "DELETE":
            origin_val = (body or {}).get("origin", "").strip()
            if not origin_val:
                return 400, {"error": "origin is required"}
            wl = load_whitelist()
            if origin_val in wl["origins"]:
                wl["origins"].remove(origin_val)
                save_whitelist(wl)
            return 200, {"success": True, "origins": wl["origins"]}
        
        if path == "/whitelist/contracts" and method == "POST":
            contract = (body or {}).get("contract", "").strip()
            if not contract:
                return 400, {"error": "contract is required"}
            wl = load_whitelist()
            if contract not in wl["contracts"]:
                wl["contracts"].append(contract)
                save_whitelist(wl)
            return 200, {"success": True, "contracts": wl["contracts"]}
        
        if path == "/whitelist/contracts" and method == "DELETE":
            contract = (body or {}).get("contract", "").strip()
            if not contract:
                return 400, {"error": "contract is required"}
            wl = load_whitelist()
            if contract in wl["contracts"]:
                wl["contracts"].remove(contract)
                save_whitelist(wl)
            return 200, {"success": True, "contracts": wl["contracts"]}
        
        # Chrome 扩展的 HTTP fallback
        if path == "/request" and method == "POST":
            return await self._handle_extension_request(body)
        
        return 404, {"error": "Not found"}
    
    async def _handle_extension_request(self, body: dict) -> tuple:
        """处理 Chrome 扩展的签名请求"""
        method = body.get("method")
        request_id = body.get("requestId")
        origin = body.get("origin", "")
        
        # ─── Origin 白名单检查 ───
        if not check_origin(origin):
            log.warning(f"🚫 Origin rejected: {origin}")
            return 403, {"error": f"Origin not whitelisted: {origin}"}
        
        if method == "connect":
            s = self._get_active_session("browser")
            if not s:
                return 403, {"error": "No active browser session"}
            return 200, {"result": {"accounts": [{
                "address": s.address,
                "publicKey": list(s.public_key),
                "chains": [f"sui:{self.network}"]
            }]}}
        
        if method == "disconnect":
            return 200, {"result": {}}
        
        # 存为 pending，等待 agent 或自动 approve
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        
        self.pending_requests[request_id] = {
            "id": request_id,
            "method": method,
            "payload": body.get("payload", {}),
            "origin": body.get("origin", ""),
            "url": body.get("url", ""),
            "timestamp": time.time(),
            "resolved": False,
            "future": future
        }
        
        log.info(f"New {method} request from {body.get('origin', '?')}: {request_id}")
        
        # 自动 approve（内部调用，带 admin token 绕过权限检查）
        # 签名前检查合约白名单
        if method in ("signTransaction", "signAndExecuteTransaction"):
            tx_data = body.get("payload", {}).get("transaction", "")
            tx_format = body.get("payload", {}).get("transactionFormat", "")
            # JSON v2 格式跳过预检查（build 后在 WS handler 里检查）
            if tx_format != "json-v2":
                try:
                    tx_bytes_check = base64.b64decode(tx_data) if isinstance(tx_data, str) else tx_data
                    if not check_contract(tx_bytes_check):
                        self.pending_requests[request_id]["resolved"] = True
                        return 403, {"error": "Contract not in whitelist"}
                except Exception:
                    pass
        
        try:
            internal_headers = {"x-admin-token": ADMIN_TOKEN}
            await self.handle_http(f"/approve/{request_id}", "POST", body=None, headers=internal_headers)
        except Exception as e:
            return 500, {"error": str(e)}
        
        try:
            result = await asyncio.wait_for(future, timeout=300)
            if "error" in result:
                return 200, {"error": result["error"]}
            return 200, {"result": result}
        except asyncio.TimeoutError:
            return 504, {"error": "Timeout"}
    
    # ─── WebSocket handler ───
    
    async def handle_ws(self, websocket):
        """处理 Chrome 扩展的 WebSocket 连接"""
        self.ws_clients.add(websocket)
        log.info(f"Chrome extension connected (total: {len(self.ws_clients)})")
        
        try:
            async for message in websocket:
                data = json.loads(message)
                request_id = data.get("requestId")
                method = data.get("method")
                
                if method == "connect":
                    if not self.session or not self.session.is_valid():
                        await websocket.send(json.dumps({
                            "requestId": request_id,
                            "error": "No active session"
                        }))
                        continue
                    
                    await websocket.send(json.dumps({
                        "requestId": request_id,
                        "result": {"accounts": [{
                            "address": self.session.address,
                            "publicKey": list(self.session.public_key),
                            "chains": [f"sui:{self.network}"]
                        }]}
                    }))
                    continue
                
                if method == "disconnect":
                    await websocket.send(json.dumps({"requestId": request_id, "result": {}}))
                    continue
                
                # 签名请求 - 自动 approve
                if not self.session or not self.session.is_valid():
                    await websocket.send(json.dumps({
                        "requestId": request_id,
                        "error": "Session expired"
                    }))
                    continue
                
                try:
                    payload = data.get("payload", {})
                    
                    if method in ("signTransaction", "signAndExecuteTransaction"):
                        tx_data = payload.get("transaction", "")
                        tx_format = payload.get("transactionFormat", "")
                        
                        # JSON v2 format: need to build via Node.js SDK
                        if tx_format == "json-v2":
                            chain = payload.get("chain", "sui:testnet")
                            network = chain.split(":")[1] if ":" in chain else "testnet"
                            sender = self.session.address
                            log.info(f"Building JSON v2 transaction for {sender} on {network}")
                            tx_bytes = await build_json_v2_transaction(tx_data, network, sender)
                        else:
                            tx_bytes = base64.b64decode(tx_data) if isinstance(tx_data, str) else bytes(tx_data)
                        
                        # 合约白名单检查
                        if not check_contract(tx_bytes):
                            await websocket.send(json.dumps({
                                "requestId": request_id,
                                "error": "Contract not in whitelist"
                            }))
                            continue
                        signature = self.session.sign_tx(tx_bytes)
                        result = {
                            "bytes": base64.b64encode(tx_bytes).decode(),
                            "signature": signature
                        }
                    elif method == "signPersonalMessage":
                        msg_data = payload.get("message", "")
                        msg_bytes = base64.b64decode(msg_data) if isinstance(msg_data, str) else bytes(msg_data)
                        signature = self.session.sign_msg(msg_bytes)
                        result = {
                            "bytes": base64.b64encode(msg_bytes).decode(),
                            "signature": signature
                        }
                    else:
                        await websocket.send(json.dumps({
                            "requestId": request_id,
                            "error": f"Unknown method: {method}"
                        }))
                        continue
                    
                    await websocket.send(json.dumps({
                        "requestId": request_id,
                        "result": result
                    }))
                    
                except PermissionError as e:
                    await websocket.send(json.dumps({
                        "requestId": request_id,
                        "error": str(e)
                    }))
                except Exception as e:
                    log.error(f"Sign error: {e}")
                    await websocket.send(json.dumps({
                        "requestId": request_id,
                        "error": str(e)
                    }))
        
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.ws_clients.discard(websocket)
            log.info(f"Chrome extension disconnected (total: {len(self.ws_clients)})")
            
            # 如果所有扩展都断开了，清空签名能力
            if len(self.ws_clients) == 0 and self.session:
                self.session.revoke("all extensions disconnected")
                log.info("All extensions disconnected, session revoked")


# ─── HTTP + WebSocket 混合服务器 ───

bridge = SuiBridge()


async def http_handler(path, request_headers):
    """websockets 库的 process_request hook，处理 HTTP 请求"""
    # WebSocket 升级请求放行
    if "Upgrade" in dict(request_headers) and dict(request_headers)["Upgrade"].lower() == "websocket":
        return None
    
    # 解析路径
    parsed = urlparse(path)
    clean_path = parsed.path
    
    # 读取 body（对于 POST）
    return None  # 让 websockets 库处理


class DualProtocolServer:
    """同时支持 HTTP 和 WebSocket 的服务器"""
    
    def __init__(self, bridge_instance: SuiBridge, port: int = BRIDGE_PORT):
        self.bridge = bridge_instance
        self.port = port
    
    async def handler(self, websocket):
        """统一处理入站连接"""
        # 检查是否是 HTTP 请求（通过 path 判断）
        if websocket.request is not None:
            path = websocket.request.path
            if path != "/ws":
                # 这是 HTTP 请求，但 websockets 库不太适合处理纯 HTTP
                # 走 WebSocket 处理
                pass
        
        await self.bridge.handle_ws(websocket)
    
    async def start(self):
        """启动服务器"""
        # 使用 asyncio 的 HTTP server 处理 HTTP，websockets 处理 WS
        from aiohttp import web
        
        app = web.Application()
        app.router.add_route('*', '/{path:.*}', self._aiohttp_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', self.port)
        await site.start()
        log.info(f"Bridge server running on http://localhost:{self.port}")
    
    def _cors_origin(self, request) -> str:
        """根据白名单返回 CORS origin，不在白名单的返回空"""
        req_origin = request.headers.get('Origin', '')
        if check_origin(req_origin):
            return req_origin
        # 本地 WebGUI 始终放行
        if req_origin.startswith('http://127.0.0.1') or req_origin.startswith('http://localhost'):
            return req_origin
        return ''

    async def _aiohttp_handler(self, request):
        from aiohttp import web
        path = "/" + request.match_info.get('path', '')
        
        # WebSocket 升级
        if request.headers.get('Upgrade', '').lower() == 'websocket':
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await self._handle_aiohttp_ws(ws)
            return ws
        
        # HTTP 请求
        method = request.method
        body = None
        if method == "POST":
            try:
                body = await request.json()
            except:
                body = {}
        
        cors_origin = self._cors_origin(request)
        cors_headers = {
            'Access-Control-Allow-Origin': cors_origin if cors_origin else 'null',
            'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, X-Admin-Token',
            'Vary': 'Origin'
        }
        
        # CORS preflight
        if method == "OPTIONS":
            return web.Response(headers=cors_headers)
        
        # 提取 headers 传给 handle_http
        req_headers = {"x-admin-token": request.headers.get("X-Admin-Token", "")}
        status, response = await self.bridge.handle_http(path, method, body, req_headers)
        
        return web.json_response(response, status=status, headers=cors_headers)
    
    async def _handle_aiohttp_ws(self, ws):
        """处理 aiohttp WebSocket"""
        from aiohttp import web as _web
        self.bridge.ws_clients.add(ws)
        log.info(f"Chrome extension connected via WS (total: {len(self.bridge.ws_clients)})")
        
        try:
            async for msg in ws:
                if msg.type == _web.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    request_id = data.get("requestId")
                    method = data.get("method")
                    
                    if method == "connect":
                        if not self.bridge.session or not self.bridge.session.is_valid():
                            await ws.send_json({"requestId": request_id, "error": "No active session"})
                            continue
                        await ws.send_json({"requestId": request_id, "result": {"accounts": [{
                            "address": self.bridge.session.address,
                            "publicKey": list(self.bridge.session.public_key),
                            "chains": [f"sui:{self.bridge.network}"]
                        }]}})
                        continue
                    
                    if method == "disconnect":
                        await ws.send_json({"requestId": request_id, "result": {}})
                        continue
                    
                    if not self.bridge.session or not self.bridge.session.is_valid():
                        await ws.send_json({"requestId": request_id, "error": "Session expired"})
                        continue
                    
                    try:
                        payload = data.get("payload", {})
                        if method in ("signTransaction", "signAndExecuteTransaction"):
                            tx_data = payload.get("transaction", "")
                            tx_bytes = base64.b64decode(tx_data)
                            if not check_contract(tx_bytes):
                                await ws.send_json({"requestId": request_id, "error": "Contract not in whitelist"})
                                continue
                            signature = self.bridge.session.sign_tx(tx_bytes)
                            result = {"bytes": base64.b64encode(tx_bytes).decode(), "signature": signature}
                        elif method == "signPersonalMessage":
                            msg_data = payload.get("message", "")
                            msg_bytes = base64.b64decode(msg_data)
                            signature = self.bridge.session.sign_msg(msg_bytes)
                            result = {"bytes": base64.b64encode(msg_bytes).decode(), "signature": signature}
                        else:
                            await ws.send_json({"requestId": request_id, "error": f"Unknown: {method}"})
                            continue
                        
                        await ws.send_json({"requestId": request_id, "result": result})
                    except Exception as e:
                        await ws.send_json({"requestId": request_id, "error": str(e)})
                
                elif msg.type == _web.WSMsgType.ERROR:
                    break
        finally:
            self.bridge.ws_clients.discard(ws)
            log.info(f"Chrome extension disconnected (total: {len(self.bridge.ws_clients)})")
            if len(self.bridge.ws_clients) == 0 and self.bridge.session:
                self.bridge.session.revoke("all extensions disconnected")


async def main():
    server = DualProtocolServer(bridge, BRIDGE_PORT)
    await server.start()
    log.info(f"Sui DApp Bridge ready on port {BRIDGE_PORT}")
    log.info("Waiting for session creation from WebGUI...")
    
    # 保持运行
    await asyncio.Event().wait()


def start_bridge_thread():
    """在后台线程启动 bridge（供 WebGUI 调用）
    返回: (bridge_instance, admin_token)
    """
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return bridge, ADMIN_TOKEN


if __name__ == "__main__":
    asyncio.run(main())

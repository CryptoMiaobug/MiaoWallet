#!/usr/bin/env python3
"""
MiaoWallet WebSocket Bridge Server
Chrome 扩展 ↔ ws://localhost:3847/ws ↔ Keychain 签名
"""

import asyncio
import json
import hashlib
import keyring
import websockets
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

SERVICE_ID = "openclaw_bot"
WALLET_FILE = ".wallet_addresses.json"
PORT = 3847

# ─── 钱包工具 ───

def load_addresses():
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), WALLET_FILE)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def get_sui_address():
    """获取第一个 sui 地址"""
    addrs = load_addresses()
    for name, addr in addrs.items():
        if "sui" in name.lower():
            return name, addr
    return None, None

def get_private_key(wallet_name):
    """从 Keychain 获取私钥"""
    try:
        pk = keyring.get_password(SERVICE_ID, wallet_name)
        return pk
    except Exception as e:
        print(f"❌ Keychain 读取失败: {e}")
        return None

def sign_transaction_bytes(private_key_hex, tx_bytes_b64):
    """用 Ed25519 签名交易"""
    import base64
    from nacl.signing import SigningKey

    # 解析私钥
    if private_key_hex.startswith("suiprivkey"):
        # Bech32 格式的 Sui 私钥
        import bech32
        _, data = bech32.bech32_decode(private_key_hex)
        if data is None:
            raise ValueError("Invalid bech32 private key")
        raw = bytes(bech32.convertbits(data, 5, 8, False))
        # 第一个字节是 scheme flag (0x00 = Ed25519)
        seed = raw[1:33]
    elif len(private_key_hex) == 64:
        seed = bytes.fromhex(private_key_hex)
    elif len(private_key_hex) == 128:
        seed = bytes.fromhex(private_key_hex[:64])
    else:
        # 尝试 base64
        raw = base64.b64decode(private_key_hex)
        if len(raw) == 33 and raw[0] == 0:
            seed = raw[1:33]
        elif len(raw) == 32:
            seed = raw
        elif len(raw) == 64:
            seed = raw[:32]
        else:
            raise ValueError(f"Unknown private key format (len={len(raw)})")

    signing_key = SigningKey(seed)
    verify_key = signing_key.verify_key

    # 解码交易字节
    tx_bytes = base64.b64decode(tx_bytes_b64)

    # Sui 签名: sign(intent || tx_bytes)
    # intent = [0, 0, 0] for TransactionData
    intent_msg = bytes([0, 0, 0]) + tx_bytes
    signed = signing_key.sign(intent_msg)
    signature_bytes = signed.signature  # 64 bytes

    # Sui signature format: flag(1) + sig(64) + pubkey(32) = 97 bytes
    flag = bytes([0x00])  # Ed25519
    pubkey_bytes = bytes(verify_key)
    sui_signature = flag + signature_bytes + pubkey_bytes

    return {
        "bytes": tx_bytes_b64,
        "signature": base64.b64encode(sui_signature).decode()
    }

def sign_personal_message(private_key_hex, message_b64):
    """签名个人消息"""
    import base64
    from nacl.signing import SigningKey

    if private_key_hex.startswith("suiprivkey"):
        import bech32
        _, data = bech32.bech32_decode(private_key_hex)
        raw = bytes(bech32.convertbits(data, 5, 8, False))
        seed = raw[1:33]
    elif len(private_key_hex) == 64:
        seed = bytes.fromhex(private_key_hex)
    else:
        raw = base64.b64decode(private_key_hex)
        seed = raw[1:33] if len(raw) == 33 else raw[:32]

    signing_key = SigningKey(seed)
    verify_key = signing_key.verify_key

    msg_bytes = base64.b64decode(message_b64)
    # personal message intent: [3, 0, 0]
    intent_msg = bytes([3, 0, 0]) + msg_bytes
    signed = signing_key.sign(intent_msg)

    flag = bytes([0x00])
    sui_signature = flag + signed.signature + bytes(verify_key)

    return {
        "bytes": message_b64,
        "signature": base64.b64encode(sui_signature).decode()
    }

# ─── 请求处理 ───

async def handle_request(method, payload):
    wallet_name, sui_address = get_sui_address()

    if method == "connect":
        if not sui_address:
            return {"error": "No Sui wallet found"}
        # 获取公钥
        pk_hex = get_private_key(wallet_name)
        pubkey_bytes = []
        if pk_hex:
            import base64
            from nacl.signing import SigningKey
            try:
                if pk_hex.startswith("suiprivkey"):
                    import bech32
                    _, data = bech32.bech32_decode(pk_hex)
                    raw = bytes(bech32.convertbits(data, 5, 8, False))
                    seed = raw[1:33]
                else:
                    seed = bytes.fromhex(pk_hex) if len(pk_hex) == 64 else base64.b64decode(pk_hex)[:32]
                sk = SigningKey(seed if len(seed) == 32 else seed[:32])
                pubkey_bytes = list(bytes(sk.verify_key))
            except Exception as e:
                print(f"⚠️ 获取公钥失败: {e}")
                pubkey_bytes = [0] * 32
            finally:
                pk_hex = None
                del pk_hex

        return {
            "accounts": [{
                "address": sui_address,
                "publicKey": pubkey_bytes,
                "chains": ["sui:mainnet", "sui:testnet", "sui:devnet"]
            }]
        }

    elif method == "disconnect":
        return {"ok": True}

    elif method == "signTransaction":
        pk_hex = get_private_key(wallet_name)
        if not pk_hex:
            return {"error": "Cannot access private key"}
        try:
            result = sign_transaction_bytes(pk_hex, payload.get("transaction", ""))
            return result
        except Exception as e:
            return {"error": f"Sign failed: {e}"}
        finally:
            pk_hex = None
            del pk_hex

    elif method == "signAndExecuteTransaction":
        pk_hex = get_private_key(wallet_name)
        if not pk_hex:
            return {"error": "Cannot access private key"}
        try:
            signed = sign_transaction_bytes(pk_hex, payload.get("transaction", ""))
            # 提交到 Sui RPC
            import urllib.request
            rpc_url = "https://fullnode.testnet.sui.io:443"
            rpc_body = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sui_executeTransactionBlock",
                "params": [
                    signed["bytes"],
                    [signed["signature"]],
                    payload.get("options", {"showEffects": True}),
                    "WaitForLocalExecution"
                ]
            }).encode()
            req = urllib.request.Request(rpc_url, data=rpc_body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                rpc_result = json.loads(resp.read())
            if "error" in rpc_result:
                return {"error": rpc_result["error"].get("message", str(rpc_result["error"]))}
            return rpc_result.get("result", rpc_result)
        except Exception as e:
            return {"error": f"Execute failed: {e}"}
        finally:
            pk_hex = None
            del pk_hex

    elif method == "signPersonalMessage":
        pk_hex = get_private_key(wallet_name)
        if not pk_hex:
            return {"error": "Cannot access private key"}
        try:
            result = sign_personal_message(pk_hex, payload.get("message", ""))
            return result
        except Exception as e:
            return {"error": f"Sign message failed: {e}"}
        finally:
            pk_hex = None
            del pk_hex

    else:
        return {"error": f"Unknown method: {method}"}

# ─── WebSocket 服务 ───

connected_clients = set()

async def ws_handler(websocket):
    path = websocket.request.path if hasattr(websocket, 'request') else '/ws'
    print(f"🔌 Chrome 扩展已连接 (path={path})")
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                request_id = data.get("requestId", "")
                method = data.get("method", "")
                payload = data.get("payload", {})

                print(f"📨 收到请求: {method} (id={request_id})")

                result = await handle_request(method, payload)

                if "error" in result:
                    response = {"requestId": request_id, "error": result["error"]}
                    print(f"❌ 响应: {result['error']}")
                else:
                    response = {"requestId": request_id, "result": result}
                    print(f"✅ 响应: {method} 成功")

                await websocket.send(json.dumps(response))

            except json.JSONDecodeError:
                print(f"⚠️ 无效 JSON: {message[:100]}")
            except Exception as e:
                print(f"❌ 处理错误: {e}")
                if request_id:
                    await websocket.send(json.dumps({
                        "requestId": request_id,
                        "error": str(e)
                    }))
    except websockets.exceptions.ConnectionClosed:
        print("🔌 Chrome 扩展断开连接")
    finally:
        connected_clients.discard(websocket)

# ─── HTTP fallback (POST /request) ───

class HTTPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/request":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            method = body.get("method", "")
            payload = body.get("payload", {})
            request_id = body.get("requestId", "")

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(handle_request(method, payload))
            loop.close()

            if "error" in result:
                resp = {"requestId": request_id, "error": result["error"]}
            else:
                resp = {"requestId": request_id, "result": result}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # 静默 HTTP 日志

def run_http(port):
    server = HTTPServer(("127.0.0.1", port), HTTPHandler)
    server.serve_forever()

# ─── 启动 ───

async def main():
    print("=" * 50)
    print("🔐 MiaoWallet WebSocket Bridge Server")
    print("=" * 50)

    wallet_name, sui_address = get_sui_address()
    if sui_address:
        print(f"💰 钱包: {wallet_name} → {sui_address[:10]}...{sui_address[-6:]}")
    else:
        print("⚠️  未找到 Sui 钱包")

    # 启动 HTTP fallback (端口 +1)
    http_port = PORT + 1
    http_thread = threading.Thread(target=run_http, args=(http_port,), daemon=True)
    http_thread.start()
    print(f"🌐 HTTP fallback: http://localhost:{http_port}/request")

    # 启动 WebSocket
    print(f"🔌 WebSocket: ws://localhost:{PORT}/ws")
    print(f"⏹  Ctrl+C 退出")
    print("=" * 50)

    async with websockets.serve(ws_handler, "127.0.0.1", PORT):
        await asyncio.Future()  # 永远运行

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 已关闭")

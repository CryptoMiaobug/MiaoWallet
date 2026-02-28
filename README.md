# 🐱 MiaoWallet — Secure Agent Wallet for Sui

> **Track 1: Safety & Security** — Sui × OpenClaw Agent Hackathon (DeepSurge)

MiaoWallet is a security middleware that lets AI agents operate on the Sui blockchain **without ever touching private keys**. It bridges the gap between AI autonomy and key safety through session-based signing, dual operation modes, and on-chain audit trails.

🌐 **Live Demo**: [cryptomiao.wal.app](https://cryptomiao.wal.app) (Walrus Sites)  
📦 **GitHub**: [CryptoMiaobug/MiaoWallet](https://github.com/CryptoMiaobug/MiaoWallet)

---

## The Problem

AI agents need blockchain access, but current approaches are fundamentally broken:

| Approach | Risk |
|----------|------|
| Give agent the private key | Agent compromise = total loss |
| Manual approval per tx | Defeats the purpose of automation |
| Shared `.env` files | Keys in plaintext, easily leaked |

**There is no secure, automated way for AI agents to sign transactions.**

## The Solution

MiaoWallet separates **key custody** from **transaction logic**:

```
AI Agent (OpenClaw)
       ↓ requests
   MiaoWallet Bridge
       ↓ signs (session-limited)
   macOS Keychain (keys never leave)
       ↓ submits
   Sui Network
```

The agent decides *what* to do. MiaoWallet handles *how* to sign — securely, automatically, within user-defined limits.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  OpenClaw (AI Agent)             │
│         Telegram / CLI / Autonomous Tasks        │
└──────────────┬──────────────────┬───────────────┘
               │                  │
        ┌──────▼──────┐   ┌──────▼──────┐
        │  API Mode   │   │Browser Mode │
        │  (MCP/HTTP) │   │(Extension)  │
        └──────┬──────┘   └──────┬──────┘
               │                  │
        ┌──────▼──────────────────▼──────┐
        │        MiaoWallet Bridge       │
        │   Session Manager + Whitelist  │
        │      (localhost:3847)          │
        └──────────────┬─────────────────┘
                       │
              ┌────────▼────────┐
              │  macOS Keychain │
              │  (Secure Store) │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │   Sui Network   │
              │ (Mainnet/Test)  │
              └─────────────────┘
```

---

## Two Operation Modes

### ⚡ API Mode (MCP Server)
Direct programmatic access via 10 MCP tools:

- `get_balance` / `get_address` / `list_wallets`
- `transfer_sui` / `transfer_coin`
- `swap_token` (Cetus Aggregator, 30+ DEX routing)
- `sign_transaction` (raw tx signing)
- `store_attestation` / `read_attestation` (Walrus)
- `get_session_status`

**Best for**: Known protocols, batch operations, maximum speed.

### 🌐 Browser Mode (Chrome Extension)
AI controls a real browser via OpenClaw Browser Relay:

1. Agent navigates to any DApp URL
2. Agent clicks buttons, fills forms, confirms transactions
3. Chrome Extension ("Sui Agent Wallet") intercepts signing requests
4. Bridge builds + signs the transaction via Keychain
5. Extension submits to chain

**Best for**: Any DApp with zero integration. Universal compatibility.

**Technical detail**: Supports Wallet Standard v2 (JSON v2 transactions with `UnresolvedObject` inputs). Extension detects the format, sends JSON to Bridge, which uses `@mysten/sui` SDK to `Transaction.from(json).build({ client })` → BCS bytes → sign.

---

## Security Model

### 🔐 Key Isolation
- Private keys stored in **macOS Keychain** (hardware-backed secure enclave)
- Keys never exist in files, environment variables, or agent-accessible memory
- Each Keychain access requires **user authorization popup** (biometric/password)

### ⏱ Session-Based Signing
- Time-limited sessions (e.g., 30 minutes)
- Count-limited sessions (e.g., max 10 signatures)
- Sessions auto-expire — no permanent API keys
- Instant manual revocation via WebGUI

### 🛡 Whitelist Control
- **Origin whitelist**: Only approved DApp domains can request signatures
- **Contract whitelist**: Only approved Move packages can be called
- Unauthorized requests are rejected before reaching the signing layer

### 📋 On-Chain Audit Trail
- Every transaction stored as immutable attestation on **Walrus** decentralized storage
- AI agent behavior is fully auditable and verifiable
- Attestations include: tx digest, timestamp, operation type, parameters

### 🔒 Keeper Bot Encryption
- For automated bots: private key encrypted with **PBKDF2 + Fernet**
- Decrypted only in memory at startup (password required)
- `.env` never contains plaintext keys

---

## Live Mainnet Transactions

All transactions executed by AI agent through MiaoWallet on Sui Mainnet:

| Type | Details | Explorer |
|------|---------|----------|
| Transfer | 0.1 SUI (wallet 02 → 01) | [A2mYfX...cj16](https://suiscan.xyz/mainnet/tx/A2mYfXUzXwTJBcZu9RNFvJBY2423YvruPXrH3wBKcj16) |
| Swap | 0.5 SUI → 6.05 WAL via Cetus | [CVvyus...THAG](https://suiscan.xyz/mainnet/tx/CVvyusHbuXEKANh8d7MLqi8VyRnvmYRg59iumeuhTHAG) |
| Attestation | Transfer record on Walrus | `SYaSI7...FERA` |
| Transfer | 0.01 SUI → bvlgari.sui (SuiNS) | [7tdZ64...FW1](https://suiscan.xyz/mainnet/tx/7tdZ644hwAqUEcN3tzvCrwBKYL8HetatKimy3vDGyFW1) |
| Attestation | Transfer 0.01 SUI → bvlgari.sui on Walrus | `kXAxaq...cQ0` |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| AI Agent | OpenClaw + Claude |
| Wallet Backend | Python (aiohttp + websockets + nacl) |
| Key Storage | macOS Keychain (Security framework) |
| Chrome Extension | Vanilla JS (Wallet Standard v2) |
| MCP Server | Python (10 tools) |
| DEX Integration | Cetus Aggregator SDK (Node.js) |
| Tx Builder | @mysten/sui SDK v1.45 |
| Storage | Walrus (decentralized attestation) |
| Deployment | Walrus Sites (cryptomiao.wal.app) |
| Blockchain | Sui (Mainnet + Testnet) |

---

## Project Structure

```
MiaoWallet-SecureWallet-4Openclaw/
├── miaowallet_webgui.py      # WebGUI (MiaoWallet Pro) — wallet management + session control
├── sui_bridge.py              # DApp Bridge — HTTP + WebSocket signing server (port 3847)
├── wallet_mcp_server.py       # MCP Server — 10 tools for AI agent
├── build_tx.mjs               # Transaction builder — JSON v2 → BCS bytes
├── extension/                 # Chrome Extension — "Sui Agent Wallet"
│   ├── manifest.json
│   ├── inject.js              # Wallet Standard v2 provider
│   ├── content.js             # Message bridge
│   └── background.js          # HTTP relay to Bridge
├── cetus-swap/
│   └── swap.mjs               # Cetus Aggregator integration
├── docs/
│   └── index.html             # Showcase page (GitHub Pages + Walrus Sites)
└── DEMO.md                    # Demo script (~3 min)
```

---

## Quick Start

```bash
# 1. Start WebGUI (includes Bridge on port 3847)
cd MiaoWallet-SecureWallet-4Openclaw
python3 miaowallet_webgui.py

# 2. Install Chrome Extension
# Load unpacked from extension/ directory

# 3. Configure OpenClaw MCP
# Add wallet_mcp_server.py to your OpenClaw config

# 4. Authorize a session in WebGUI
# Set time limit + sign count → Start Session

# 5. AI agent can now operate!
# "Transfer 0.01 SUI to alice.sui"
# "Swap 1 SUI to WAL"
# "Open RPS game and bet 10 USDC on Rock"
```

---

## Why Track 1: Safety & Security?

MiaoWallet directly addresses the core challenge of AI agent security on blockchain:

1. **Key isolation** — Private keys physically separated from AI agent
2. **Least privilege** — Sessions grant minimum necessary access
3. **Defense in depth** — Whitelist + session limits + Keychain + audit trail
4. **Auditability** — Every AI action recorded on Walrus (immutable)
5. **Revocability** — Instant session kill switch

The fundamental insight: **Give AI the ability to act, but never the keys to act independently.**

---

## Links

- 🌐 Live: [cryptomiao.wal.app](https://cryptomiao.wal.app)
- 📄 GitHub Pages: [cryptomiaobug.github.io/MiaoWallet](https://cryptomiaobug.github.io/MiaoWallet/)
- 💻 Source: [github.com/CryptoMiaobug/MiaoWallet](https://github.com/CryptoMiaobug/MiaoWallet)

---

*Built with 🐱 by CryptoMiao — powered by OpenClaw + Claude + Sui*

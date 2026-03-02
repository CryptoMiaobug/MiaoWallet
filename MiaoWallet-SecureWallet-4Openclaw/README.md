# MiaoWallet — AI-Native Agent Wallet for Sui

> Secure on-chain operations for AI agents. Private keys never leave your device.

## Overview

MiaoWallet is a secure wallet infrastructure that enables AI agents (via OpenClaw) to perform on-chain operations on Sui blockchain without ever exposing private keys. It combines macOS Keychain-level security with a bridge-based signing architecture, giving AI agents the ability to transfer tokens, swap on DEXs, and store attestations — all while keeping keys safely isolated.

## Why MiaoWallet?

### The Problem
AI agents need to interact with blockchain, but existing solutions either expose private keys to the agent (unsafe) or require manual human approval for every transaction (slow). There's no secure, automated way for agents to operate on-chain.

### The Solution
MiaoWallet separates **key custody** from **transaction logic**. The AI agent decides what to do; MiaoWallet handles the signing — securely, automatically, within user-defined limits.

### Key Advantages

🔐 **Hardware-Level Key Isolation** — Private keys live in macOS Keychain (secure enclave), never in files, env vars, or memory accessible to the agent. Even if the agent is compromised, keys are safe.

🤖 **Two Operation Modes — API + Browser** — Unlike traditional agent wallets that only work with specific protocols:
- **API Mode**: Direct RPC/SDK integration for maximum speed and reliability. Build transactions programmatically, sign via bridge, submit on-chain.
- **Browser Mode**: OpenClaw Browser Relay + MiaoWallet Chrome Extension. The agent controls any DApp website like a human — click buttons, fill forms, confirm transactions. **No API integration needed. Works with ANY DApp on day one.**

⏱ **Session-Based Authorization** — Users grant time-limited, count-limited signing sessions. The agent operates freely within bounds, and access auto-expires. No permanent API keys, no unlimited access.

🌐 **Universal DApp Compatibility** — Through Browser Mode, MiaoWallet can interact with any Sui DApp without writing a single line of integration code. New DEX launched? New NFT mint? New lending protocol? Just point the agent to the URL.

🔗 **Deep Sui Ecosystem Integration** — Native support for Cetus Aggregator (30+ DEXs), Walrus decentralized storage, SuiNS domain resolution, and more.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  OpenClaw   │────▶│  MCP Server  │────▶│  Bridge API     │
│  AI Agent   │     │  (10 tools)  │     │  localhost:3847  │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │   MiaoWallet    │
                                          │  (Keychain)     │
                                          │  Signs & Returns│
                                          └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │   Sui Network   │
                                          │   (Mainnet)     │
                                          └─────────────────┘
```

**Two operation modes:**

1. **Backend API Mode** — Agent builds transactions via RPC/SDK, MiaoWallet signs through bridge. Fully automated, no browser needed.
2. **Browser Mode** — Agent controls DApp websites via OpenClaw Browser Relay, MiaoWallet Chrome Extension handles signing. Works with any DApp without custom API integration.

## Features

### Security
- 🔐 **Keychain Storage** — Private keys stored in macOS Keychain, never in files or environment variables
- 🌉 **Bridge Signing** — AI agent only receives signatures, never touches private keys
- ⏱ **Session Controls** — Configurable sign count limits and time-based expiration
- 🔒 **Origin Whitelist** — Chrome Extension only connects to approved origins

### MCP Server (10 Tools)
| Tool | Description |
|------|-------------|
| `get_address` | Get connected wallet address and network |
| `get_balance` | Query token balances (SUI, USDC, etc.) |
| `get_session_status` | Check signing session status and limits |
| `list_wallets` | List all saved wallets |
| `sign_transaction` | Sign raw transaction bytes |
| `transfer_sui` | Transfer SUI to any address |
| `transfer_coin` | Transfer any token (USDC, etc.) |
| `swap_token` | DEX swap via Cetus Aggregator (30+ DEXs) |
| `store_attestation` | Store transaction attestation on Walrus |
| `read_attestation` | Read attestation from Walrus |

### DeFi Integration
- 🔄 **Cetus Aggregator** — Optimal routing across 30+ Sui DEXs (Cetus, Kriya, Aftermath, Turbos, etc.)
- 💱 **Any Token Pair** — SUI, WAL, USDC, CETUS and more

### Decentralized Attestation
- 📦 **Walrus Storage** — Transaction records stored on Walrus decentralized storage
- 🔗 **Verifiable** — Anyone can read attestations with Blob ID
- 📋 **Immutable** — On-chain proof of every agent operation

## Demo Transactions (Mainnet)

| Operation | TX Digest | Details |
|-----------|-----------|---------|
| Transfer | `A2mYfXUzXwTJBcZu9RNFvJBY2423YvruPXrH3wBKcj16` | 0.1 SUI transfer (wallet 02 → 01) |
| Swap | `CVvyusHbuXEKANh8d7MLqi8VyRnvmYRg59iumeuhTHAG` | 0.5 SUI → 6.05 WAL via Cetus |
| Attestation | Blob: `SYaSI7HXpyuH8eoVrZOYvaD01idV8gV5CvXILmTfERA` | Transfer record on Walrus |

## Tech Stack

- **Wallet**: Python + macOS Keychain + WebSocket Bridge
- **MCP Server**: Python (FastMCP) — 10 tools for OpenClaw integration
- **Swap Engine**: Node.js + Cetus Aggregator SDK
- **Attestation**: Walrus CLI (decentralized blob storage)
- **Extension**: Chrome Extension (Sui wallet standard)
- **Blockchain**: Sui (Mainnet)

## Project Structure

```
MiaoWallet/
├── wallet_mcp_server.py    # MCP Server (10 tools)
├── ws_bridge.py            # WebSocket bridge for signing
├── miaowallet_webgui.py    # WebGUI for wallet management
├── mnemonic_manager_bip44.py # BIP44 key derivation
├── sui_transfer.py         # SUI transfer with dry-run
├── sui_dry_run.js          # Transaction simulation
├── sui_name_service.js     # SuiNS domain resolution
├── cetus-swap/
│   ├── swap.mjs            # Cetus Aggregator swap script
│   └── CETUS_DOCS.md       # SDK reference docs
├── extension/              # Chrome Extension
├── SKILL.md                # OpenClaw skill definition
└── README.md               # This file
```

## Quick Start

### Prerequisites
- macOS with Keychain Access
- Python 3.10+
- Node.js 18+
- OpenClaw installed

### Setup
```bash
# Install Python dependencies
python3 -m venv venv && source venv/bin/activate
pip install keyring pynacl bech32 requests httpx mcp

# Install Node dependencies
npm install
cd cetus-swap && npm install && cd ..

# Install Walrus CLI
curl -sSfL https://raw.githubusercontent.com/Mystenlabs/suiup/main/install.sh | sh
suiup install walrus
```

### Run
```bash
# Start WebGUI (connect wallet & authorize session)
python3 miaowallet_webgui.py

# MCP Server is configured in OpenClaw and runs automatically
```

## Security Model

```
User (you)                          AI Agent (bot)
    │                                    │
    ├── Owns private keys (Keychain)     ├── Builds transactions
    ├── Authorizes sessions (WebGUI)     ├── Calls MCP tools
    ├── Sets sign limits & time          ├── Receives signatures only
    └── Can revoke anytime               └── Cannot access keys
```

The AI agent CANNOT:
- Access or extract private keys
- Modify session parameters
- Sign beyond authorized limits
- Operate after session expires

## Built With

Built for **Sui x OpenClaw Agent Hackathon** by [@miao](https://t.me/kamiaorich)

## License

Apache 2.0

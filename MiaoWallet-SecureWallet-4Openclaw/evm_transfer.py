#!/usr/bin/env python3
"""
EVM 转账脚本 (支持 ETH、USDC 等代币)
使用 macOS Keychain 存储私钥
"""

import keyring
import json
import argparse
import sys
import os
from web3 import Web3
from eth_account import Account
from decimal import Decimal

SERVICE_ID = "openclaw_bot"
REGISTRY_KEY = "__wallet_registry__"

# 默认 RPC 端点 (可以配置)
DEFAULT_RPC = {
    "ethereum": "https://eth.llamarpc.com",
    "arbitrum": "https://arbitrum.llamarpc.com",
    "optimism": "https://optimism.llamarpc.com",
    "base": "https://base.llamarpc.com",
    "polygon": "https://polygon.llamarpc.com"
}

# 常用代币合约地址
TOKEN_ADDRESSES = {
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F"
    },
    "arbitrum": {
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"
    },
    "optimism": {
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"
    },
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    },
    "polygon": {
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    }
}

def get_wallet_info(alias):
    """从注册表获取钱包信息"""
    data = keyring.get_password(SERVICE_ID, REGISTRY_KEY)
    if not data:
        return None
    
    try:
        wallets = json.loads(data)
        for w in wallets:
            if w.get("alias") == alias:
                return w
    except Exception:
        pass
    return None

def get_private_key(alias):
    """从 Keychain 获取私钥"""
    try:
        pk = keyring.get_password(SERVICE_ID, alias)
        if not pk:
            print(f"❌ 无法从 Keychain 获取私钥: {alias}")
            return None
        return pk
    except Exception as e:
        print(f"❌ Keychain 访问错误: {e}")
        return None

def get_web3_instance(network="ethereum"):
    """获取 Web3 实例"""
    rpc_url = DEFAULT_RPC.get(network)
    if not rpc_url:
        print(f"❌ 不支持的网络: {network}")
        return None
    
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            print(f"❌ 无法连接到 {network} RPC: {rpc_url}")
            return None
        return w3
    except Exception as e:
        print(f"❌ 连接错误: {e}")
        return None

def get_native_balance(w3, address):
    """获取原生代币余额 (ETH, MATIC, etc.)"""
    try:
        balance_wei = w3.eth.get_balance(address)
        balance_eth = w3.from_wei(balance_wei, 'ether')
        return balance_eth
    except Exception as e:
        print(f"❌ 获取余额错误: {e}")
        return Decimal('0')

def get_token_balance(w3, token_address, wallet_address):
    """获取 ERC20 代币余额"""
    try:
        # ERC20 ABI (仅 balanceOf 和 decimals)
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            }
        ]
        
        contract = w3.eth.contract(address=token_address, abi=abi)
        balance = contract.functions.balanceOf(wallet_address).call()
        decimals = contract.functions.decimals().call()
        return balance / (10 ** decimals)
    except Exception as e:
        print(f"❌ 获取代币余额错误: {e}")
        return Decimal('0')

def send_native_token(w3, private_key, to_address, amount, network="ethereum"):
    """发送原生代币 (ETH, MATIC, etc.)"""
    try:
        account = Account.from_key(private_key)
        from_address = account.address
        
        # 获取当前 gas 价格
        gas_price = w3.eth.gas_price
        
        # 估算 gas
        gas_estimate = 21000  # 标准转账
        
        # 计算总费用
        total_cost = gas_estimate * gas_price
        
        # 检查余额
        balance = w3.eth.get_balance(from_address)
        amount_wei = w3.to_wei(amount, 'ether')
        
        if balance < amount_wei + total_cost:
            print(f"❌ 余额不足")
            print(f"   需要: {w3.from_wei(amount_wei + total_cost, 'ether')} {network.upper()}")
            print(f"   当前: {w3.from_wei(balance, 'ether')} {network.upper()}")
            return None
        
        # 构建交易
        nonce = w3.eth.get_transaction_count(from_address)
        
        tx = {
            'nonce': nonce,
            'to': to_address,
            'value': amount_wei,
            'gas': gas_estimate,
            'gasPrice': gas_price,
            'chainId': w3.eth.chain_id
        }
        
        # 签名交易
        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        
        # 发送交易
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        return tx_hash.hex()
        
    except Exception as e:
        print(f"❌ 转账错误: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description='EVM 转账脚本')
    parser.add_argument('alias', help='钱包别名')
    parser.add_argument('to_address', help='收款地址')
    parser.add_argument('amount', type=float, help='转账金额')
    parser.add_argument('--network', default='ethereum', help='网络 (ethereum, arbitrum, optimism, base, polygon)')
    parser.add_argument('--token', default='native', help='代币类型 (native, USDC, USDT, DAI)')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不实际执行')
    parser.add_argument('--yes', action='store_true', help='跳过确认直接执行')
    
    args = parser.parse_args()
    
    # 获取钱包信息
    wallet_info = get_wallet_info(args.alias)
    if not wallet_info:
        print(f"❌ 找不到钱包: {args.alias}")
        sys.exit(1)
    
    if wallet_info.get('chain') != 'evm':
        print(f"❌ 钱包 {args.alias} 不是 EVM 钱包")
        sys.exit(1)
    
    # 获取私钥
    private_key = get_private_key(args.alias)
    if not private_key:
        sys.exit(1)
    
    # 获取 Web3 实例
    w3 = get_web3_instance(args.network)
    if not w3:
        sys.exit(1)
    
    account = Account.from_key(private_key)
    from_address = account.address
    
    print(f"🔐 发送方: {args.alias} ({from_address})")
    print(f"📍 收款方: {args.to_address}")
    print(f"🌐 网络: {args.network}")
    print(f"💰 代币: {args.token}")
    print(f"📊 金额: {args.amount}")
    
    # 检查地址有效性
    if not w3.is_address(args.to_address):
        print(f"❌ 无效的收款地址: {args.to_address}")
        sys.exit(1)
    
    # 获取余额
    if args.token == 'native':
        balance = get_native_balance(w3, from_address)
        print(f"📈 当前余额: {balance} {args.network.upper()}")
    else:
        token_address = TOKEN_ADDRESSES.get(args.network, {}).get(args.token)
        if not token_address:
            print(f"❌ 网络 {args.network} 不支持代币 {args.token}")
            sys.exit(1)
        
        balance = get_token_balance(w3, token_address, from_address)
        print(f"📈 当前 {args.token} 余额: {balance}")
    
    # 预览模式
    if args.dry_run:
        print("\n✅ 预览完成 (dry-run 模式)")
        print("   实际执行请使用 --yes 参数")
        return
    
    # 确认
    if not args.yes:
        confirm = input("\n确认转账？(y/n): ").lower()
        if confirm != 'y':
            print("❌ 转账已取消")
            return
    
    print("\n⏳ 正在执行转账...")
    
    # 执行转账
    if args.token == 'native':
        tx_hash = send_native_token(w3, private_key, args.to_address, args.amount, args.network)
    else:
        print(f"❌ 代币转账功能暂未实现 (仅支持原生代币)")
        sys.exit(1)
    
    if tx_hash:
        print(f"✅ 转账成功!")
        print(f"🔗 交易哈希: {tx_hash}")
        
        # 根据网络生成浏览器链接
        explorers = {
            "ethereum": "https://etherscan.io/tx/",
            "arbitrum": "https://arbiscan.io/tx/",
            "optimism": "https://optimistic.etherscan.io/tx/",
            "base": "https://basescan.org/tx/",
            "polygon": "https://polygonscan.com/tx/"
        }
        
        explorer = explorers.get(args.network)
        if explorer:
            print(f"🌐 查看交易: {explorer}{tx_hash}")
    else:
        print("❌ 转账失败")

if __name__ == "__main__":
    main()
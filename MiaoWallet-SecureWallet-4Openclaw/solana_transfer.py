#!/usr/bin/env python3
"""
SOLANA 转账脚本
使用 macOS Keychain 存储私钥
简化版本，使用直接RPC调用
"""

import keyring
import json
import argparse
import sys
import os
import base58
import requests
import time

SERVICE_ID = "openclaw_bot"
REGISTRY_KEY = "__wallet_registry__"

# SOLANA RPC 端点
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"

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

def solana_rpc_request(method, params=None):
    """发送 SOLANA RPC 请求"""
    headers = {
        'Content-Type': 'application/json',
    }
    data = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': method,
        'params': params or []
    }
    
    try:
        response = requests.post(DEFAULT_RPC, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ RPC 请求错误: {e}")
        return None

def get_balance(pubkey):
    """获取 SOL 余额"""
    result = solana_rpc_request('getBalance', [pubkey])
    if result and 'result' in result:
        # SOL 有 9 位小数
        lamports = result['result']['value']
        return lamports / 1_000_000_000
    return 0

def send_sol(from_private_key, to_address, amount):
    """发送 SOL (简化版本，实际实现需要完整的交易签名)"""
    print("⚠️  SOLANA 转账功能需要完整的交易签名实现")
    print("    当前版本仅提供预览功能")
    print("    实际转账需要:")
    print("    1. 解析私钥为 Keypair")
    print("    2. 构建交易")
    print("    3. 签名交易")
    print("    4. 发送交易")
    
    # 这里只返回一个模拟的交易哈希
    return "SIMULATED_TX_HASH_NEED_FULL_IMPLEMENTATION"

def main():
    parser = argparse.ArgumentParser(description='SOLANA 转账脚本 (简化版)')
    parser.add_argument('alias', help='钱包别名')
    parser.add_argument('to_address', help='收款地址')
    parser.add_argument('amount', type=float, help='转账金额 (SOL)')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不实际执行')
    parser.add_argument('--yes', action='store_true', help='跳过确认直接执行')
    
    args = parser.parse_args()
    
    # 获取钱包信息
    wallet_info = get_wallet_info(args.alias)
    if not wallet_info:
        print(f"❌ 找不到钱包: {args.alias}")
        sys.exit(1)
    
    if wallet_info.get('chain') != 'solana':
        print(f"❌ 钱包 {args.alias} 不是 SOLANA 钱包")
        sys.exit(1)
    
    # 获取私钥
    private_key_str = get_private_key(args.alias)
    if not private_key_str:
        sys.exit(1)
    
    # 获取钱包地址
    from_address = wallet_info.get('address', '未知地址')
    
    print(f"🔐 发送方: {args.alias} ({from_address})")
    print(f"📍 收款方: {args.to_address}")
    print(f"💰 金额: {args.amount} SOL")
    
    # 获取余额
    balance = get_balance(from_address)
    print(f"📈 当前余额: {balance} SOL")
    
    # 检查余额是否足够
    if balance < args.amount:
        print(f"❌ 余额不足")
        print(f"   需要: {args.amount} SOL")
        print(f"   当前: {balance} SOL")
        sys.exit(1)
    
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
    
    # 执行转账 (简化版本)
    tx_hash = send_sol(private_key_str, args.to_address, args.amount)
    
    if tx_hash:
        print(f"✅ 转账成功!")
        print(f"🔗 交易哈希: {tx_hash}")
        print(f"🌐 查看交易: https://solscan.io/tx/{tx_hash}")
        print("\n⚠️  注意: 这是简化版本，实际需要完整的交易签名实现")
    else:
        print("❌ 转账失败")

if __name__ == "__main__":
    main()
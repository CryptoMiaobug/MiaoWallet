#!/usr/bin/env python3
"""
强制清理所有旧数据
确保重新导入时使用BIP44算法
"""

import os
import json
import sys
import keyring

def force_clean():
    """强制清理所有数据"""
    print("🔧 强制清理所有旧数据...")
    
    # 1. 删除钱包数据文件
    wallet_file = os.path.join(os.path.dirname(__file__), ".wallet_addresses.json")
    if os.path.exists(wallet_file):
        os.remove(wallet_file)
        print(f"✅ 删除钱包数据文件: {wallet_file}")
    else:
        print(f"ℹ️  钱包数据文件不存在: {wallet_file}")
    
    # 2. 清理Keychain
    service_name = "openclaw_bot"
    try:
        # 尝试删除所有可能的Keychain条目
        import subprocess
        
        # 查找所有相关条目
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service_name],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            # 删除服务
            subprocess.run(["security", "delete-generic-password", "-s", service_name], 
                          capture_output=True)
            print("✅ 删除Keychain服务")
        else:
            print("ℹ️  Keychain中没有找到相关服务")
            
    except Exception as e:
        print(f"⚠️  清理Keychain时出错: {e}")
    
    # 3. 创建空的数据文件
    with open(wallet_file, 'w') as f:
        json.dump({}, f)
    
    print(f"✅ 创建空的数据文件: {wallet_file}")
    
    print("\n🎉 清理完成！")
    print("\n📋 下一步:")
    print("1. 重启MiaoWallet Pro网页版")
    print("2. 打开浏览器访问: http://127.0.0.1:63796")
    print("3. 点击'导入助记词'按钮")
    print("4. 输入OKX助记词:")
    print("   price dutch rack marble another amateur option hidden hammer measure insane language")
    print("5. 检查生成的地址是否与OKX一致")

if __name__ == "__main__":
    print("=" * 60)
    print("MiaoWallet Pro - 强制清理工具")
    print("=" * 60)
    
    response = input("\n⚠️  这将删除所有钱包数据。是否继续? (y/N): ")
    if response.lower() != 'y':
        print("操作取消")
        sys.exit(0)
    
    force_clean()
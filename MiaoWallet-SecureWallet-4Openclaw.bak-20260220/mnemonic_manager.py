#!/usr/bin/env python3
"""
助记词管理器 - 支持BIP39/BIP44多链钱包生成
"""

import json
import os
import sys
import hashlib
import hmac
import binascii
from typing import Dict, List, Tuple, Optional
import keyring

class MnemonicManager:
    """助记词管理器，支持多链钱包生成"""
    
    def __init__(self):
        self.service_name = "openclaw_bot"
        self.wallet_file = os.path.join(os.path.dirname(__file__), ".wallet_addresses.json")
        
    def validate_mnemonic(self, mnemonic: str) -> bool:
        """
        验证助记词有效性（BIP39标准）
        简化版本：检查单词数量
        """
        words = mnemonic.strip().split()
        
        # BIP39标准：12, 15, 18, 21, 24个单词
        valid_lengths = {12, 15, 18, 21, 24}
        
        if len(words) not in valid_lengths:
            return False
        
        # 这里可以添加更复杂的验证（校验和检查）
        # 但为了简化，我们先只检查长度
        return True
    
    def generate_wallet_from_mnemonic(self, mnemonic: str, wallet_name: str) -> Dict:
        """
        从助记词生成多链钱包
        返回：{chain: address} 字典
        """
        if not self.validate_mnemonic(mnemonic):
            raise ValueError("无效的助记词")
        
        # 生成种子
        seed = self._mnemonic_to_seed(mnemonic)
        
        # 为不同链生成地址（简化版本）
        # 实际应该使用BIP44路径和相应SDK
        wallets = {}
        
        # SUI地址（示例）
        sui_address = self._generate_sui_address(seed, wallet_name)
        wallets["SUI"] = sui_address
        
        # Solana地址（示例）
        solana_address = self._generate_solana_address(seed, wallet_name)
        wallets["Solana"] = solana_address
        
        # EVM地址（示例）
        evm_address = self._generate_evm_address(seed, wallet_name)
        wallets["EVM"] = evm_address
        
        return wallets
    
    def _mnemonic_to_seed(self, mnemonic: str, passphrase: str = "") -> bytes:
        """
        将助记词转换为种子（PBKDF2）
        简化版本
        """
        # 实际应该使用：hmac.new(b"mnemonic" + passphrase.encode(), mnemonic.encode(), hashlib.sha512).digest()
        # 这里简化处理
        mnemonic_bytes = mnemonic.encode('utf-8')
        passphrase_bytes = passphrase.encode('utf-8')
        
        # 使用简单哈希作为种子（实际应该用PBKDF2）
        combined = mnemonic_bytes + passphrase_bytes
        seed = hashlib.sha256(combined).digest()
        
        return seed
    
    def _generate_sui_address(self, seed: bytes, wallet_name: str) -> str:
        """生成SUI地址（示例）"""
        # 实际应该使用SUI SDK生成地址
        # 这里生成示例地址
        hash_obj = hashlib.sha256(seed + wallet_name.encode())
        hex_hash = hash_obj.hexdigest()[:64]  # 64字符哈希
        
        # 格式化为SUI地址格式
        sui_address = f"0x{hex_hash}"
        return sui_address
    
    def _generate_solana_address(self, seed: bytes, wallet_name: str) -> str:
        """生成Solana地址（示例）"""
        # 实际应该使用Solana SDK生成地址
        hash_obj = hashlib.sha256(seed + b"solana" + wallet_name.encode())
        base58_hash = self._bytes_to_base58(hash_obj.digest()[:32])
        return base58_hash
    
    def _generate_evm_address(self, seed: bytes, wallet_name: str) -> str:
        """生成EVM地址（示例）"""
        # 实际应该使用eth-keys或web3.py生成地址
        hash_obj = hashlib.sha256(seed + b"evm" + wallet_name.encode())
        hex_hash = hash_obj.hexdigest()[:40]  # 20字节 = 40字符
        
        # 格式化为EVM地址格式
        evm_address = f"0x{hex_hash}"
        return evm_address
    
    def _bytes_to_base58(self, b: bytes) -> str:
        """将字节转换为Base58（简化版本）"""
        # Base58字符集（比特币/ Solana使用）
        alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        
        # 简化版本：直接使用hex
        return b.hex()
    
    def save_mnemonic_to_keychain(self, mnemonic: str, wallet_name: str) -> bool:
        """将助记词保存到Keychain"""
        try:
            # 保存助记词
            keyring.set_password(
                self.service_name,
                f"mnemonic_{wallet_name}",
                mnemonic
            )
            return True
        except Exception as e:
            print(f"保存助记词到Keychain失败: {e}")
            return False
    
    def save_wallet_addresses(self, wallet_name: str, addresses: Dict) -> bool:
        """保存钱包地址到文件"""
        try:
            # 加载现有钱包
            if os.path.exists(self.wallet_file):
                with open(self.wallet_file, 'r') as f:
                    wallets = json.load(f)
            else:
                wallets = {}
            
            # 为每个链创建独立条目
            for chain, address in addresses.items():
                entry_name = f"{wallet_name}_{chain.lower()}"
                wallets[entry_name] = address
            
            # 保存回文件
            with open(self.wallet_file, 'w') as f:
                json.dump(wallets, f, indent=2)
            
            return True
        except Exception as e:
            print(f"保存钱包地址失败: {e}")
            return False
    
    def get_all_wallets(self) -> Dict:
        """获取所有钱包"""
        try:
            if os.path.exists(self.wallet_file):
                with open(self.wallet_file, 'r') as f:
                    return json.load(f)
            return {}
        except:
            return {}
    
    def delete_wallet(self, wallet_name: str) -> bool:
        """删除钱包"""
        try:
            # 从Keychain删除助记词
            try:
                keyring.delete_password(self.service_name, f"mnemonic_{wallet_name}")
            except:
                pass
            
            # 从文件删除相关条目
            if os.path.exists(self.wallet_file):
                with open(self.wallet_file, 'r') as f:
                    wallets = json.load(f)
                
                # 删除所有相关条目
                keys_to_delete = []
                for key in wallets.keys():
                    if key.startswith(f"{wallet_name}_"):
                        keys_to_delete.append(key)
                
                for key in keys_to_delete:
                    del wallets[key]
                
                # 保存回文件
                with open(self.wallet_file, 'w') as f:
                    json.dump(wallets, f, indent=2)
            
            return True
        except Exception as e:
            print(f"删除钱包失败: {e}")
            return False

# 测试函数
def test_mnemonic_manager():
    """测试助记词管理器"""
    print("🧪 测试助记词管理器...")
    
    manager = MnemonicManager()
    
    # 测试助记词
    test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    
    print(f"1. 验证助记词: {manager.validate_mnemonic(test_mnemonic)}")
    
    # 生成钱包
    print("2. 生成多链钱包...")
    wallets = manager.generate_wallet_from_mnemonic(test_mnemonic, "test_wallet")
    
    for chain, address in wallets.items():
        print(f"   {chain}: {address}")
    
    # 保存测试
    print("3. 保存到Keychain...")
    saved = manager.save_mnemonic_to_keychain(test_mnemonic, "test_wallet")
    print(f"   保存结果: {saved}")
    
    print("4. 保存地址到文件...")
    saved = manager.save_wallet_addresses("test_wallet", wallets)
    print(f"   保存结果: {saved}")
    
    print("5. 获取所有钱包...")
    all_wallets = manager.get_all_wallets()
    print(f"   钱包数量: {len(all_wallets)}")
    
    print("✅ 测试完成")

if __name__ == "__main__":
    test_mnemonic_manager()
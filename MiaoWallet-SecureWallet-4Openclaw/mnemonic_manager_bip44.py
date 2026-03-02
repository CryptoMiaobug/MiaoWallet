#!/usr/bin/env python3
"""
Mnemonic Manager with BIP44 Standard and OKX Compatibility
"""

import hashlib
import hmac
import struct
import os
import json
import base58
from typing import Dict, Optional, Tuple, List
from nacl.signing import SigningKey
from eth_keys import keys
from eth_utils import to_checksum_address

class MnemonicManagerBIP44:
    """
    BIP44标准助记词管理器
    支持SUI, Ethereum, Solana
    兼容OKX钱包
    """
    
    def __init__(self):
        # 支持的链和对应的coin_type
        self.SUPPORTED_CHAINS = ["SUI", "Ethereum", "Solana"]
        self.COIN_TYPES = {
            "SUI": 784,
            "Ethereum": 60,
            "Solana": 501
        }
        
        # BIP44 purpose
        self.BIP44_PURPOSE = 44
        
        # 钱包数据文件
        self.wallet_dir = os.path.dirname(os.path.abspath(__file__))
        self.wallet_file = os.path.join(self.wallet_dir, ".wallet_addresses.json")
    
    def validate_mnemonic(self, mnemonic: str) -> bool:
        """验证助记词格式"""
        words = mnemonic.strip().split()
        return len(words) in [12, 15, 18, 21, 24]
    
    def bip39_mnemonic_to_seed(self, mnemonic: str, passphrase: str = "") -> bytes:
        """BIP39种子生成"""
        mnemonic_bytes = mnemonic.encode('utf-8')
        salt = f"mnemonic{passphrase}".encode('utf-8')
        
        # PBKDF2-HMAC-SHA512
        seed = hashlib.pbkdf2_hmac(
            'sha512',
            mnemonic_bytes,
            salt,
            iterations=2048,
            dklen=64
        )
        
        return seed
    
    def bip32_derive(self, parent_key: bytes, chain_code: bytes, index: int, hardened: bool = False) -> tuple:
        """
        BIP32: 派生子密钥
        完整版本 (标准BIP32算法)
        """
        if hardened:
            # 硬化派生: index + 0x80000000
            index = index | 0x80000000
            data = bytes([0]) + parent_key + struct.pack('>I', index)
        else:
            # 非硬化派生需要公钥
            try:
                priv_key_obj = keys.PrivateKey(parent_key)
                pub_key = priv_key_obj.public_key
                pub_key_compressed = pub_key.to_compressed_bytes()  # 压缩公钥，33字节
                data = pub_key_compressed + struct.pack('>I', index)
            except Exception as e:
                print(f"⚠️  非硬化派生错误: {e}")
                # 回退到使用私钥
                data = parent_key + struct.pack('>I', index)
        
        # HMAC-SHA512
        I = hmac.new(chain_code, data, hashlib.sha512).digest()
        left_32_bytes = I[:32]
        child_chain_code = I[32:]
        
        # 完整BIP32算法: 椭圆曲线点加法
        # 将left_32_bytes和parent_key转换为整数
        k_par = int.from_bytes(parent_key, 'big')
        k_i = int.from_bytes(left_32_bytes, 'big')
        
        # 椭圆曲线阶 (secp256k1)
        n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        
        # 子私钥 = (k_par + k_i) mod n
        child_private_key_int = (k_par + k_i) % n
        
        # 转换回字节
        child_private_key = child_private_key_int.to_bytes(32, 'big')
        
        return child_private_key, child_chain_code
    
    def slip10_derive_ed25519(self, parent_key: bytes, chain_code: bytes, index: int) -> tuple:
        """
        SLIP-0010派生 (Ed25519)
        根据B的算法详解：子私钥 = HMAC输出前32字节
        Ed25519只支持硬化派生
        """
        # Ed25519只支持硬化派生
        index = index | 0x80000000  # 硬化
        
        # 数据格式: 0x00 + 父私钥 + index (大端4字节)
        data = bytes([0]) + parent_key + struct.pack('>I', index)
        
        # HMAC-SHA512
        I = hmac.new(chain_code, data, hashlib.sha512).digest()
        
        # ✅ 修复：SLIP-0010算法，子私钥就是HMAC输出的前32字节
        child_private_key = I[:32]
        child_chain_code = I[32:]
        
        return child_private_key, child_chain_code
    
    def derive_bip44_path(self, seed: bytes, coin_type: int, account: int = 0, change: int = 0, address_index: int = 0, all_hardened: bool = False) -> bytes:
        """
        派生BIP44路径
        all_hardened=True: 全部硬化 (OKX SUI模式)
        """
        # 根据coin_type选择主密钥种子字符串
        # ✅ 修复：区分secp256k1和ed25519的主密钥种子
        if coin_type == 784:  # SUI (ed25519)
            master_seed_string = b"ed25519 seed"
        elif coin_type == 501:  # Solana (ed25519)
            master_seed_string = b"ed25519 seed"
        else:  # ETH/EVM (secp256k1)
            master_seed_string = b"Bitcoin seed"
        
        # 从种子生成主密钥
        h = hmac.new(master_seed_string, seed, hashlib.sha512).digest()
        master_private_key = h[:32]
        master_chain_code = h[32:]
        
        # 根据coin_type选择派生算法
        # SUI (784) 和 Solana (501) 使用Ed25519算法，其他使用secp256k1算法
        use_ed25519 = (coin_type == 784 or coin_type == 501)  # SUI 和 Solana
        
        # 派生路径
        
        # 1. m/44' (硬化)
        if use_ed25519:
            key, chain_code = self.slip10_derive_ed25519(master_private_key, master_chain_code, self.BIP44_PURPOSE)
        else:
            key, chain_code = self.bip32_derive(master_private_key, master_chain_code, self.BIP44_PURPOSE, hardened=True)
        
        # 2. m/44'/coin_type' (硬化)
        if use_ed25519:
            key, chain_code = self.slip10_derive_ed25519(key, chain_code, coin_type)
        else:
            key, chain_code = self.bip32_derive(key, chain_code, coin_type, hardened=True)
        
        # 3. m/44'/coin_type'/account' (硬化)
        if use_ed25519:
            key, chain_code = self.slip10_derive_ed25519(key, chain_code, account)
        else:
            key, chain_code = self.bip32_derive(key, chain_code, account, hardened=True)
        
        # 4. m/44'/coin_type'/account'/change (或change')
        if all_hardened:
            # OKX模式: change层也硬化
            if use_ed25519:
                key, chain_code = self.slip10_derive_ed25519(key, chain_code, change)
            else:
                key, chain_code = self.bip32_derive(key, chain_code, change, hardened=True)
        else:
            # 标准模式: change层不硬化
            if use_ed25519:
                # Ed25519只支持硬化派生，所以这里也硬化
                key, chain_code = self.slip10_derive_ed25519(key, chain_code, change)
            else:
                key, chain_code = self.bip32_derive(key, chain_code, change, hardened=False)
        
        # 5. m/44'/coin_type'/account'/change/address_index (或address_index')
        if all_hardened:
            # OKX模式: address_index层也硬化
            if use_ed25519:
                key, chain_code = self.slip10_derive_ed25519(key, chain_code, address_index)
            else:
                key, chain_code = self.bip32_derive(key, chain_code, address_index, hardened=True)
        else:
            # 标准模式: address_index层不硬化
            if use_ed25519:
                # Ed25519只支持硬化派生，所以这里也硬化
                key, chain_code = self.slip10_derive_ed25519(key, chain_code, address_index)
            else:
                key, chain_code = self.bip32_derive(key, chain_code, address_index, hardened=False)
        
        return key
    
    def generate_sui_address(self, private_key: bytes) -> str:
        """从私钥生成SUI地址 (OKX兼容格式)"""
        if len(private_key) < 32:
            private_key = hashlib.sha256(private_key).digest()[:32]
        else:
            private_key = private_key[:32]
        
        signing_key = SigningKey(private_key)
        verify_key = signing_key.verify_key
        public_key = verify_key.encode()
        
        # ✅ 修复：SUI地址是公钥的Blake2b哈希 (与OKX一致)
        # 根据OKX地址格式: 0xd77c0024ef63145551eb5fb2519b841d2d3e377d65c1f3aab936ee8b461bb2f7
        # 算法: Blake2b(scheme + public_key)，其中scheme=0
        
        hasher = hashlib.blake2b(digest_size=32)
        hasher.update(bytes([0]) + public_key)  # scheme = 0
        hash_bytes = hasher.digest()
        
        # SUI地址就是公钥的Blake2b哈希
        sui_address = "0x" + hash_bytes.hex()
        
        return sui_address
    
    def generate_ethereum_address(self, private_key: bytes) -> str:
        """从私钥生成Ethereum地址"""
        if len(private_key) < 32:
            private_key = hashlib.sha256(private_key).digest()[:32]
        else:
            private_key = private_key[:32]
        
        # 使用eth_keys生成地址
        private_key_obj = keys.PrivateKey(private_key)
        public_key = private_key_obj.public_key
        
        # ✅ 修复：使用真正的keccak256，不是SHA3-256
        try:
            from Crypto.Hash import keccak
            # ✅ 修复：使用64字节公钥（没有0x04前缀）
            # 根据测试，ETH地址生成应该使用64字节公钥
            pubkey_bytes = public_key.to_bytes()  # 64字节，没有前缀
            
            k = keccak.new(digest_bits=256, data=pubkey_bytes)
            hash_bytes = k.digest()
        except ImportError:
            # 回退到SHA3-256（不准确，但可用）
            keccak_hash = hashlib.sha3_256()
            pubkey_bytes = public_key.to_bytes()  # 64字节，没有前缀
            keccak_hash.update(pubkey_bytes)
            hash_bytes = keccak_hash.digest()
            print("⚠️  警告：使用SHA3-256代替keccak256，地址可能不准确")
        
        # 取后20字节作为地址
        address = '0x' + hash_bytes[-20:].hex()
        
        # 添加校验和
        address = to_checksum_address(address)
        
        return address
    
    def generate_solana_address_slip0010(self, mnemonic: str, account_index: int = 0) -> str:
        """
        使用SLIP-0010算法生成Solana地址
        兼容OKX
        """
        # 生成种子
        seed = self.bip39_mnemonic_to_seed(mnemonic)
        
        # SLIP-0010主密钥
        I = hmac.new(b"ed25519 seed", seed, hashlib.sha512).digest()
        master_private_key = I[:32]
        master_chain_code = I[32:]
        
        # 派生路径: m/44'/501'/account'/0'
        path = [44, 501, account_index, 0]
        
        key = master_private_key
        chain_code = master_chain_code
        
        for index in path:
            index = index | 0x80000000  # 硬化
            data = bytes([0]) + key + struct.pack('>I', index)
            
            I = hmac.new(chain_code, data, hashlib.sha512).digest()
            left_32_bytes = I[:32]
            chain_code = I[32:]
            
            key = left_32_bytes
        
        # 生成公钥
        signing_key = SigningKey(key[:32])
        verify_key = signing_key.verify_key
        public_key = verify_key.encode()
        
        # Base58编码
        address = base58.b58encode(public_key).decode()
        
        return address
    
    def generate_wallet_from_mnemonic(self, mnemonic: str, wallet_name: str, account_index: int = 0, address_index: int = 0) -> Dict:
        """
        从助记词生成多链钱包 (BIP44标准)
        自动检测OKX助记词并使用OKX地址
        """
        if not self.validate_mnemonic(mnemonic):
            raise ValueError("无效的助记词")
        
        # 不再需要OKX兼容性检测，使用算法生成地址
        
        # 生成种子 (BIP39)
        seed = self.bip39_mnemonic_to_seed(mnemonic)
        
        wallets = {}
        
        # 为每个支持的链生成地址
        for chain in self.SUPPORTED_CHAINS:
            coin_type = self.COIN_TYPES.get(chain)
            if coin_type is None:
                continue
            
            # 生成地址
            if chain == "SUI":
                # SUI使用全部硬化模式 (OKX兼容)
                private_key = self.derive_bip44_path(seed, coin_type, account_index, 0, address_index, all_hardened=True)
                address = self.generate_sui_address(private_key)
            
            elif chain == "Ethereum":
                # Ethereum使用标准BIP44模式
                private_key = self.derive_bip44_path(seed, coin_type, account_index, 0, address_index, all_hardened=False)
                address = self.generate_ethereum_address(private_key)
            
            elif chain == "Solana":
                # Solana 路径: m/44'/501'/account'/0'
                # OKX 多钱包通过递增 account 层实现
                address = self.generate_solana_address_slip0010(mnemonic, account_index)
            
            else:
                continue
            
            wallets[chain] = address
        
        return wallets
    
    # 不再需要硬编码OKX地址方法，使用算法生成

    def save_wallet_addresses(self, wallet_name: str, addresses: Dict) -> bool:
        """保存钱包地址到文件"""
        try:
            if os.path.exists(self.wallet_file):
                with open(self.wallet_file, 'r') as f:
                    wallets = json.load(f)
            else:
                wallets = {}

            for chain, address in addresses.items():
                # 统一用小写链名作后缀
                entry_name = f"{wallet_name}_{chain.lower()}"
                wallets[entry_name] = address

            with open(self.wallet_file, 'w') as f:
                json.dump(wallets, f, indent=2)
            return True
        except Exception as e:
            print(f"保存钱包地址失败: {e}")
            return False

    def delete_wallet(self, wallet_name: str) -> bool:
        """删除钱包的所有链地址"""
        try:
            if os.path.exists(self.wallet_file):
                with open(self.wallet_file, 'r') as f:
                    wallets = json.load(f)

                keys_to_delete = [k for k in wallets if k == wallet_name or k.startswith(f"{wallet_name}_")]
                for k in keys_to_delete:
                    del wallets[k]

                with open(self.wallet_file, 'w') as f:
                    json.dump(wallets, f, indent=2)

            # 清理 Keychain
            try:
                import keyring
                keyring.delete_password("openclaw_bot", f"mnemonic_{wallet_name}")
            except Exception:
                pass
            try:
                import keyring
                keyring.delete_password("openclaw_bot", f"nickname_{wallet_name}")
            except Exception:
                pass

            return True
        except Exception as e:
            print(f"删除钱包失败: {e}")
            return False

    def generate_next_wallet(self, mnemonic: str, existing_wallets: list) -> Tuple[Dict, str]:
        """
        OKX 兼容的多钱包生成。不同链递增策略不同：
        - SUI:  递增 account  → m/44'/784'/N'/0'/0'
        - ETH:  递增 address_index → m/44'/60'/0'/0/N
        - Solana: 递增 account → m/44'/501'/N'/0'
        返回 (wallets_dict, wallet_name)
        """
        next_index = len(existing_wallets)
        wallet_name = f"wallet_{next_index}"

        if not self.validate_mnemonic(mnemonic):
            raise ValueError("无效的助记词")

        seed = self.bip39_mnemonic_to_seed(mnemonic)
        wallets = {}

        # SUI: 递增 account
        pk = self.derive_bip44_path(seed, 784, account=next_index, change=0, address_index=0, all_hardened=True)
        wallets["SUI"] = self.generate_sui_address(pk)

        # ETH: 递增 address_index
        pk = self.derive_bip44_path(seed, 60, account=0, change=0, address_index=next_index, all_hardened=False)
        wallets["Ethereum"] = self.generate_ethereum_address(pk)

        # Solana: 递增 account
        wallets["Solana"] = self.generate_solana_address_slip0010(mnemonic, next_index)

        return wallets, wallet_name

# 测试代码
if __name__ == "__main__":
    manager = MnemonicManagerBIP44()
    
    # 测试OKX助记词
    okx_mnemonic = "price dutch rack marble another amateur option hidden hammer measure insane language"
    
    print("🔍 测试OKX助记词:")
    wallets = manager.generate_wallet_from_mnemonic(okx_mnemonic, "okx_wallet", 0, 0)
    
    for chain, address in wallets.items():
        print(f"{chain}: {address}")
    
    print()
    
    # 测试标准助记词
    test_mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    
    print("🔍 测试标准助记词:")
    wallets = manager.generate_wallet_from_mnemonic(test_mnemonic, "test_wallet", 0, 0)
    
    for chain, address in wallets.items():
        print(f"{chain}: {address}")
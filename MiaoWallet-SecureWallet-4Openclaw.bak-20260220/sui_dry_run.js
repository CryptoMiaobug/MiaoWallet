#!/usr/bin/env node
/**
 * sui_dry_run.js — Sui 交易 Dry Run 预览工具
 * 
 * 在签名前模拟执行交易，显示：
 * - 💰 资产余额变化（哪些币增减多少）
 * - 📦 对象变化（创建/修改/删除了什么）
 * - ⛽ Gas 费用预估
 * - ✅/❌ 交易是否会成功
 * 
 * 依赖: @mysten/sui v2.4.0+
 * 用法: node sui_dry_run.js <base64_tx_bytes> [network]
 */

const { SuiJsonRpcClient } = require('@mysten/sui/jsonRpc');

const NETWORKS = {
  mainnet: 'https://fullnode.mainnet.sui.io:443',
  testnet: 'https://fullnode.testnet.sui.io:443',
  devnet:  'https://fullnode.devnet.sui.io:443',
};

/**
 * Dry Run a transaction
 * @param {string} txBytes - base64 encoded BCS transaction data
 * @param {string} network - mainnet | testnet | devnet
 */
async function dryRunTransaction(txBytes, network = 'mainnet') {
  const url = NETWORKS[network];
  if (!url) throw new Error(`Unknown network: ${network}`);
  const client = new SuiJsonRpcClient({ url });
  return await client.dryRunTransactionBlock({ transactionBlock: txBytes });
}

/**
 * Format Dry Run result for human reading
 */
function formatDryRunResult(result) {
  const lines = [];
  const status = result.effects?.status?.status;

  lines.push(`\n${'='.repeat(50)}`);
  lines.push(`  📋 Sui 交易 Dry Run 预览`);
  lines.push(`${'='.repeat(50)}`);
  lines.push(`\n状态: ${status === 'success' ? '✅ 交易将会成功' : '❌ 交易将会失败'}`);

  if (status !== 'success' && result.effects?.status?.error) {
    lines.push(`错误: ${result.effects.status.error}`);
  }

  // Gas
  const gas = result.effects?.gasUsed;
  if (gas) {
    const totalGas = (
      BigInt(gas.computationCost || 0) +
      BigInt(gas.storageCost || 0) -
      BigInt(gas.storageRebate || 0) +
      BigInt(gas.nonRefundableStorageFee || 0)
    );
    lines.push(`\n⛽ Gas 费用预估:`);
    lines.push(`   计算费: ${gas.computationCost} MIST`);
    lines.push(`   存储费: ${gas.storageCost} MIST`);
    lines.push(`   存储退款: -${gas.storageRebate} MIST`);
    lines.push(`   总计: ${totalGas.toString()} MIST (${(Number(totalGas) / 1e9).toFixed(6)} SUI)`);
  }

  // Balance changes
  if (result.balanceChanges && result.balanceChanges.length > 0) {
    lines.push(`\n💰 资产余额变化:`);
    for (const change of result.balanceChanges) {
      const amount = BigInt(change.amount);
      const coinType = change.coinType?.split('::').pop() || change.coinType;
      const direction = amount > 0n ? '📈 收到' : '📉 支出';
      const absAmount = amount > 0n ? amount : -amount;
      const addr = change.owner?.AddressOwner || change.owner?.ObjectOwner || '?';
      const shortAddr = addr.length > 10 ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : addr;
      lines.push(`   ${direction} ${(Number(absAmount) / 1e9).toFixed(6)} ${coinType}`);
      lines.push(`      地址: ${shortAddr}`);
    }
  }

  // Object changes
  if (result.objectChanges && result.objectChanges.length > 0) {
    lines.push(`\n📦 对象变化:`);
    const emoji = { created: '🆕', mutated: '✏️', deleted: '🗑️', wrapped: '📦', published: '📤' };
    for (const obj of result.objectChanges) {
      const e = emoji[obj.type] || '❓';
      const objType = obj.objectType?.split('::').slice(-2).join('::') || '';
      lines.push(`   ${e} ${obj.type}: ${objType}`);
      if (obj.objectId) {
        lines.push(`      ID: ${obj.objectId.slice(0, 10)}...`);
      }
    }
  }

  // Events
  if (result.events && result.events.length > 0) {
    lines.push(`\n📡 事件 (${result.events.length} 个):`);
    for (const evt of result.events.slice(0, 5)) {
      const evtType = evt.type?.split('::').slice(-2).join('::') || evt.type;
      lines.push(`   • ${evtType}`);
    }
    if (result.events.length > 5) {
      lines.push(`   ... 还有 ${result.events.length - 5} 个事件`);
    }
  }

  lines.push(`\n${'='.repeat(50)}\n`);
  return lines.join('\n');
}

// CLI
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length < 1) {
    console.log('用法: node sui_dry_run.js <base64_tx_bytes> [network]');
    console.log('  network: mainnet (默认) | testnet | devnet');
    process.exit(1);
  }
  const [txBytes, network = 'mainnet'] = args;
  dryRunTransaction(txBytes, network)
    .then(result => console.log(formatDryRunResult(result)))
    .catch(err => {
      console.error('❌ Dry Run 失败:', err.message);
      process.exit(1);
    });
}

module.exports = { dryRunTransaction, formatDryRunResult, NETWORKS };

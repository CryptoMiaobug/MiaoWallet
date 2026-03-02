/**
 * Cetus Aggregator Swap via MiaoWallet Bridge
 * 用法: node swap.mjs <from> <to> <amount> [slippage%]
 * 例: node swap.mjs SUI WAL 0.5 1
 */

import { AggregatorClient, Env } from '@cetusprotocol/aggregator-sdk';
import { SuiClient } from '@mysten/sui/client';
import { Transaction } from '@mysten/sui/transactions';
import BN from 'bn.js';

const BRIDGE_URL = 'http://127.0.0.1:3847';
const SUI_RPC = 'https://fullnode.mainnet.sui.io:443';

const COIN_TYPES = {
  SUI: '0x2::sui::SUI',
  WAL: '0x356a26eb9e012a68958082340d4c4116e7f55615cf27affcff209cf0ae544f59::wal::WAL',
  USDC: '0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC',
  CETUS: '0x06864a6f921804860930db6ddbe2e16acdf8504495ea7481637a1c8b9a8fe54b::cetus::CETUS',
};

const DECIMALS = { SUI: 9, WAL: 9, USDC: 6, CETUS: 9 };

async function bridgeGet(path) {
  const res = await fetch(`${BRIDGE_URL}${path}`);
  return res.json();
}

async function bridgePost(path, data) {
  const res = await fetch(`${BRIDGE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return res.json();
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 3) {
    console.log('用法: node swap.mjs <from> <to> <amount> [slippage%]');
    console.log('例: node swap.mjs SUI WAL 0.5 1');
    console.log('支持:', Object.keys(COIN_TYPES).join(', '));
    process.exit(1);
  }

  const fromSymbol = args[0].toUpperCase();
  const toSymbol = args[1].toUpperCase();
  const amount = parseFloat(args[2]);
  const slippagePct = parseFloat(args[3] || '1');

  const fromType = COIN_TYPES[fromSymbol];
  const toType = COIN_TYPES[toSymbol];
  if (!fromType || !toType) {
    console.error(`❌ 不支持: ${fromSymbol} 或 ${toSymbol}`);
    process.exit(1);
  }

  // 获取钱包地址
  const addrData = await bridgeGet('/address');
  if (addrData.error) {
    console.error(`❌ ${addrData.error}`);
    process.exit(1);
  }
  const wallet = addrData.address;
  console.log(`🔐 钱包: ${wallet.slice(0, 10)}...${wallet.slice(-6)}`);
  console.log(`🔄 ${amount} ${fromSymbol} → ${toSymbol} (滑点 ${slippagePct}%)`);

  // 初始化
  const suiClient = new SuiClient({ url: SUI_RPC });
  const client = new AggregatorClient({
    signer: wallet,
    client: suiClient,
    env: Env.Mainnet,
  });

  // 计算 raw amount
  const fromDecimals = DECIMALS[fromSymbol];
  const toDecimals = DECIMALS[toSymbol];
  const amountRaw = Math.floor(amount * (10 ** fromDecimals)).toString();

  // 查找最优路由
  console.log('🔍 查找最优路由...');
  const routers = await client.findRouters({
    from: fromType,
    target: toType,
    amount: new BN(amountRaw),
    byAmountIn: true,
  });

  if (!routers) {
    console.error('❌ 找不到可用路由');
    process.exit(1);
  }

  const estimatedOut = routers.amountOut.toString();
  const estimatedOutHuman = (parseInt(estimatedOut) / (10 ** toDecimals)).toFixed(6);
  console.log(`💰 预估获得: ${estimatedOutHuman} ${toSymbol}`);

  // 构建交易
  console.log('🔨 构建交易...');
  const txb = new Transaction();
  txb.setSender(wallet);
  txb.setGasBudget(500_000_000);

  await client.fastRouterSwap({
    router: routers,
    txb,
    slippage: slippagePct / 100,
    refreshAllCoins: true,
  });

  // 序列化
  const txBytes = await txb.build({ client: suiClient });
  const txBase64 = Buffer.from(txBytes).toString('base64');
  console.log(`📦 交易大小: ${txBytes.length} bytes`);

  // 通过 bridge 签名
  console.log('✍️ 签名中...');
  const signData = await bridgePost('/sign-raw', { txBytes: txBase64 });
  if (signData.error) {
    console.error(`❌ 签名失败: ${signData.error}`);
    process.exit(1);
  }
  console.log('✅ 签名成功');

  // 提交交易
  console.log('📤 提交交易...');
  const execRes = await fetch(SUI_RPC, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1,
      method: 'sui_executeTransactionBlock',
      params: [txBase64, [signData.signature], { showEffects: true, showBalanceChanges: true }, 'WaitForLocalExecution'],
    }),
  });
  const execResult = await execRes.json();

  if (execResult.error) {
    console.error(`❌ 提交失败: ${JSON.stringify(execResult.error)}`);
    process.exit(1);
  }

  const effects = execResult.result?.effects || {};
  const status = effects.status?.status;
  const digest = execResult.result?.digest;

  if (status === 'success') {
    console.log(`\n✅ Swap 成功！`);
    console.log(`💸 ${amount} ${fromSymbol} → ~${estimatedOutHuman} ${toSymbol}`);
    console.log(`🔗 tx: ${digest}`);

    const balanceChanges = execResult.result?.balanceChanges || [];
    if (balanceChanges.length > 0) {
      console.log('\n📊 余额变化:');
      for (const bc of balanceChanges) {
        const sym = Object.entries(COIN_TYPES).find(([_, v]) => v === bc.coinType)?.[0] || bc.coinType.split('::').pop();
        const dec = DECIMALS[sym] || 9;
        const change = parseInt(bc.amount) / (10 ** dec);
        console.log(`   ${change > 0 ? '+' : ''}${change.toFixed(6)} ${sym}`);
      }
    }
  } else {
    console.error(`❌ 交易失败: ${status}`);
    console.log(`🔗 tx: ${digest}`);
  }
}

main().catch(err => {
  console.error('❌ 错误:', err.message || err);
  process.exit(1);
});

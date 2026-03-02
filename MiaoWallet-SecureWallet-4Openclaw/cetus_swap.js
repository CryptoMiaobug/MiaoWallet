/**
 * Cetus DEX Swap via MiaoWallet Bridge
 * 用法: node cetus_swap.js <from_coin> <to_coin> <amount> [slippage%]
 * 例: node cetus_swap.js SUI WAL 0.5 1
 */

const { initCetusSDK, adjustForSlippage, d, Percentage, TransactionUtil } = require('@cetusprotocol/cetus-sui-clmm-sdk');
const { Transaction } = require('@mysten/sui/transactions');
const BN = require('bn.js') || (x => BigInt(x));

const BRIDGE_URL = 'http://127.0.0.1:3847';
const SUI_RPC = 'https://fullnode.mainnet.sui.io:443';

// 已知的 mainnet coin types
const COIN_TYPES = {
  SUI: '0x2::sui::SUI',
  WAL: '0x356a26eb9e012a68958082340d4c4116e7f55615cf27affcff209cf0ae544f59::wal::WAL',
  USDC: '0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC',
};

const DECIMALS = {
  SUI: 9,
  WAL: 9,
  USDC: 6,
};

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

async function findPool(sdk, coinTypeA, coinTypeB) {
  // 尝试搜索池子
  const pools = await sdk.Pool.getPoolByCoins([coinTypeA, coinTypeB]);
  if (pools && pools.length > 0) {
    // 选流动性最大的
    let best = pools[0];
    for (const p of pools) {
      if (BigInt(p.liquidity || 0) > BigInt(best.liquidity || 0)) {
        best = p;
      }
    }
    return best;
  }
  return null;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 3) {
    console.log('用法: node cetus_swap.js <from> <to> <amount> [slippage%]');
    console.log('例: node cetus_swap.js SUI WAL 0.5 1');
    process.exit(1);
  }

  const fromSymbol = args[0].toUpperCase();
  const toSymbol = args[1].toUpperCase();
  const amount = parseFloat(args[2]);
  const slippagePct = parseFloat(args[3] || '1'); // 默认 1%

  const fromType = COIN_TYPES[fromSymbol];
  const toType = COIN_TYPES[toSymbol];
  if (!fromType || !toType) {
    console.error(`❌ 不支持的代币: ${fromSymbol} 或 ${toSymbol}`);
    console.log('支持:', Object.keys(COIN_TYPES).join(', '));
    process.exit(1);
  }

  // 获取钱包地址
  const addrData = await bridgeGet('/address');
  if (addrData.error) {
    console.error(`❌ ${addrData.error}`);
    process.exit(1);
  }
  const address = addrData.address;
  console.log(`🔐 钱包: ${address.slice(0, 10)}...${address.slice(-6)}`);
  console.log(`🔄 ${amount} ${fromSymbol} → ${toSymbol} (滑点 ${slippagePct}%)`);

  // 初始化 Cetus SDK
  const sdk = initCetusSDK({ network: 'mainnet', fullNodeUrl: SUI_RPC });
  sdk.senderAddress = address;

  // 查找池子
  console.log('🔍 查找交易池...');
  
  // 确定 a2b 方向
  let pool = null;
  let a2b = true;
  
  // 先尝试 from=A, to=B
  pool = await findPool(sdk, fromType, toType);
  if (pool) {
    a2b = true;
  } else {
    // 反过来试
    pool = await findPool(sdk, toType, fromType);
    if (pool) {
      a2b = false;
    }
  }

  if (!pool) {
    console.error(`❌ 找不到 ${fromSymbol}/${toSymbol} 交易池`);
    process.exit(1);
  }

  console.log(`✅ 池子: ${pool.poolAddress.slice(0, 10)}...`);
  console.log(`   coinA: ${pool.coinTypeA.split('::').pop()}`);
  console.log(`   coinB: ${pool.coinTypeB.split('::').pop()}`);
  console.log(`   方向: ${a2b ? 'A→B' : 'B→A'}`);

  // 计算输入金额
  const fromDecimals = DECIMALS[fromSymbol];
  const amountRaw = Math.floor(amount * (10 ** fromDecimals)).toString();

  // 预估 swap
  console.log('📊 预估兑换...');
  const decimalsA = a2b ? DECIMALS[fromSymbol] : DECIMALS[toSymbol];
  const decimalsB = a2b ? DECIMALS[toSymbol] : DECIMALS[fromSymbol];

  const preswapRes = await sdk.Swap.preswap({
    pool: pool,
    currentSqrtPrice: pool.current_sqrt_price,
    coinTypeA: pool.coinTypeA,
    coinTypeB: pool.coinTypeB,
    decimalsA,
    decimalsB,
    a2b,
    byAmountIn: true,
    amount: amountRaw,
  });

  if (!preswapRes || preswapRes.isExceed) {
    console.error('❌ 兑换金额超出池子容量');
    process.exit(1);
  }

  const estimatedOut = preswapRes.estimatedAmountOut;
  const toDecimals = DECIMALS[toSymbol];
  const estimatedOutHuman = (parseInt(estimatedOut) / (10 ** toDecimals)).toFixed(6);
  console.log(`💰 预估获得: ${estimatedOutHuman} ${toSymbol}`);
  console.log(`⛽ 手续费: ${(parseInt(preswapRes.estimatedFeeAmount) / (10 ** fromDecimals)).toFixed(6)} ${fromSymbol}`);

  // 计算滑点保护
  const slippage = Percentage.fromDecimal(d(slippagePct / 100));
  const toAmount = new BN(estimatedOut.toString());
  const amountLimit = adjustForSlippage(toAmount, slippage, false);
  console.log(`🛡 最小获得: ${(parseInt(amountLimit.toString()) / (10 ** toDecimals)).toFixed(6)} ${toSymbol}`);

  // 构建 swap 交易
  console.log('🔨 构建交易...');
  const swapPayload = await sdk.Swap.createSwapTransactionWithoutTransferCoinsPayload({
    pool_id: pool.poolAddress,
    a2b,
    by_amount_in: true,
    amount: amountRaw,
    amount_limit: amountLimit.toString(),
    coinTypeA: pool.coinTypeA,
    coinTypeB: pool.coinTypeB,
  });

  // 把输出 coin 转回自己
  TransactionUtil.buildTransferCoinToSender(sdk, swapPayload.tx, swapPayload.coinABs[0], pool.coinTypeA);
  TransactionUtil.buildTransferCoinToSender(sdk, swapPayload.tx, swapPayload.coinABs[1], pool.coinTypeB);

  // 序列化交易
  const txBytes = await swapPayload.tx.build({ client: sdk.fullClient });
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
    
    // 显示余额变化
    const balanceChanges = execResult.result?.balanceChanges || [];
    if (balanceChanges.length > 0) {
      console.log('\n📊 余额变化:');
      for (const bc of balanceChanges) {
        const symbol = bc.coinType.split('::').pop();
        const dec = DECIMALS[symbol] || 9;
        const change = parseInt(bc.amount) / (10 ** dec);
        console.log(`   ${change > 0 ? '+' : ''}${change.toFixed(6)} ${symbol}`);
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

#!/usr/bin/env node
/**
 * sui_name_service.js — SuiNS 域名解析工具
 * 
 * 功能：
 * - 🔍 域名 → 地址 (resolve)
 * - 🔍 地址 → 域名 (reverse)
 * - ✅ 域名格式验证
 * - 📋 查询域名详情（所有者、过期时间等）
 * 
 * 依赖: @mysten/sui v2.4.0+, @mysten/suins v1.0.2+
 * 用法:
 *   node sui_name_service.js resolve <name.sui>
 *   node sui_name_service.js reverse <0x地址>
 *   node sui_name_service.js validate <name.sui>
 */

const { SuiJsonRpcClient } = require('@mysten/sui/jsonRpc');
const { normalizeSuiNSName, isValidSuiNSName } = require('@mysten/sui/utils');

const NETWORKS = {
  mainnet: 'https://fullnode.mainnet.sui.io:443',
  testnet: 'https://fullnode.testnet.sui.io:443',
  devnet:  'https://fullnode.devnet.sui.io:443',
};

function getClient(network = 'mainnet') {
  return new SuiJsonRpcClient({ url: NETWORKS[network] });
}

/**
 * 域名 → 地址
 */
async function resolveNameToAddress(name, network = 'mainnet') {
  const client = getClient(network);
  const normalized = normalizeSuiNSName(name);
  const address = await client.resolveNameServiceAddress({ name: normalized });
  return address;
}

/**
 * 地址 → 域名列表
 */
async function resolveAddressToNames(address, network = 'mainnet') {
  const client = getClient(network);
  const result = await client.resolveNameServiceNames({ address });
  return result.data || [];
}

/**
 * 智能解析：输入域名或地址，返回 { address, names }
 */
async function smartResolve(input, network = 'mainnet') {
  input = input.trim();
  
  // 如果是地址格式 (0x...)
  if (input.startsWith('0x') && input.length >= 42) {
    const names = await resolveAddressToNames(input, network);
    return {
      input,
      type: 'address',
      address: input,
      names,
      primaryName: names[0] || null,
    };
  }
  
  // 如果是域名格式
  let name = input;
  if (!name.includes('.') && !name.includes('@')) {
    name = `${name}.sui`; // 自动补 .sui
  }
  
  if (!isValidSuiNSName(name)) {
    return { input, type: 'invalid', error: `无效的 SuiNS 域名: ${name}` };
  }
  
  const address = await resolveNameToAddress(name, network);
  if (!address) {
    return { input, type: 'domain', name, address: null, error: '域名未注册或未绑定地址' };
  }
  
  return { input, type: 'domain', name, address };
}

/**
 * 格式化输出
 */
function formatResult(result) {
  const lines = [];
  lines.push(`\n${'─'.repeat(45)}`);
  lines.push(`  🌐 SuiNS 域名解析`);
  lines.push(`${'─'.repeat(45)}`);
  
  if (result.error && !result.address) {
    lines.push(`\n❌ ${result.error}`);
    lines.push(`   输入: ${result.input}`);
  } else if (result.type === 'address') {
    lines.push(`\n📍 地址: ${result.address}`);
    if (result.names && result.names.length > 0) {
      lines.push(`🏷️  绑定域名:`);
      result.names.forEach((n, i) => {
        const tag = i === 0 ? ' (主域名)' : '';
        lines.push(`   ${i + 1}. ${n}${tag}`);
      });
    } else {
      lines.push(`🏷️  该地址未绑定任何 SuiNS 域名`);
    }
  } else if (result.type === 'domain') {
    lines.push(`\n🏷️  域名: ${result.name}`);
    if (result.address) {
      lines.push(`📍 解析地址: ${result.address}`);
    } else {
      lines.push(`❌ ${result.error}`);
    }
  }
  
  lines.push(`\n${'─'.repeat(45)}\n`);
  return lines.join('\n');
}

// CLI
if (require.main === module) {
  const [cmd, input, network = 'mainnet'] = process.argv.slice(2);
  
  if (!cmd || !input) {
    console.log(`用法:
  node sui_name_service.js resolve <name.sui> [network]    域名 → 地址
  node sui_name_service.js reverse <0x地址>  [network]     地址 → 域名
  node sui_name_service.js smart   <域名或地址> [network]   智能解析
  node sui_name_service.js validate <name.sui>             验证域名格式

  network: mainnet (默认) | testnet | devnet`);
    process.exit(1);
  }
  
  if (cmd === 'validate') {
    const valid = isValidSuiNSName(input.includes('.') ? input : `${input}.sui`);
    console.log(valid ? `✅ "${input}" 是有效的 SuiNS 域名` : `❌ "${input}" 不是有效的 SuiNS 域名`);
    process.exit(valid ? 0 : 1);
  }
  
  const fn = cmd === 'reverse' 
    ? resolveAddressToNames(input, network).then(names => ({ input, type: 'address', address: input, names }))
    : cmd === 'resolve'
    ? resolveNameToAddress(input, network).then(addr => ({ input, type: 'domain', name: input, address: addr, error: addr ? null : '域名未注册或未绑定地址' }))
    : smartResolve(input, network);
  
  fn.then(r => console.log(formatResult(r)))
    .catch(err => { console.error('❌ 解析失败:', err.message); process.exit(1); });
}

module.exports = { resolveNameToAddress, resolveAddressToNames, smartResolve, formatResult, isValidSuiNSName, normalizeSuiNSName };

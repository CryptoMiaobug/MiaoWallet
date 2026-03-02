#!/usr/bin/env node
/**
 * Build a Sui Transaction from JSON v2 format to BCS bytes.
 * Uses @mysten/sui v1 SDK (from cetus-swap/node_modules).
 * Usage: echo '<json>' | node build_tx.mjs <network> <sender>
 * Output: JSON { bytes: "<base64>" } or { error: "<msg>" }
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url + '/../cetus-swap/');
const { Transaction } = require('@mysten/sui/transactions');
const { SuiClient } = require('@mysten/sui/client');

const network = process.argv[2] || 'testnet';
const sender = process.argv[3];

const rpcUrl = `https://fullnode.${network}.sui.io:443`;
const client = new SuiClient({ url: rpcUrl });

let input = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) {
  input += chunk;
}

try {
  const tx = Transaction.from(input);
  if (sender) tx.setSender(sender);
  
  const bytes = await tx.build({ client });
  const b64 = Buffer.from(bytes).toString('base64');
  process.stdout.write(JSON.stringify({ bytes: b64 }));
} catch (e) {
  process.stdout.write(JSON.stringify({ error: e.message }));
  process.exit(1);
}

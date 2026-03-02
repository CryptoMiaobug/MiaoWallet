/**
 * Sui Agent Wallet - Background Service Worker
 * 通过 HTTP 与本地 MiaoWallet Bridge (localhost:3847) 通信
 */

const BRIDGE_URL = 'http://127.0.0.1:3847';

// ─── HTTP 请求 ───

const sendRequest = async (method, payload, meta = {}) => {
  const requestId = `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  
  const resp = await fetch(`${BRIDGE_URL}/request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ requestId, method, payload, ...meta })
  });
  
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data.result;
};

// ─── 处理 content script 消息 ───

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== 'SUI_AGENT_REQUEST') return false;
  
  const { method, payload, origin, url } = message;
  
  sendRequest(method, payload, { origin, url, tabId: sender.tab?.id })
    .then(result => sendResponse({ result }))
    .catch(error => sendResponse({ error: error.message }));
  
  return true;
});

console.log('[Sui Agent Wallet] Background service worker ready');

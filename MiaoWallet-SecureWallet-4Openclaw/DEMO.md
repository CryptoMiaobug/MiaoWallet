# MiaoWallet Demo 脚本（约 3 分钟）

## 参赛信息
- 赛道：Track 1 — Safety & Security
- 项目：MiaoWallet — AI Agent 的安全钱包中间层
- 网站：https://cryptomiao.wal.app（Walrus Sites 去中心化部署）
- GitHub：https://github.com/CryptoMiaobug/MiaoWellet-SecureWallet-4Openclaw

---

## 1. 开场 — 项目介绍（20s）
- 打开 Walrus Sites（cryptomiao.wal.app）
- 展示架构图：OpenClaw → MiaoWallet → Sui（API / Browser 双模式）
- 一句话定位："MiaoWallet 是 AI Agent 和区块链之间的安全中间层，让 AI 能操作钱包但碰不到私钥"
- 快速滚动展示 Live TX 记录（真实链上交易，非 mock）

## 2. MiaoWallet WebGUI（20s）
- 打开 WebGUI（MiaoWallet Pro）
- 展示钱包列表 + 余额自动加载
- 展示双模式 Session 面板（API + Browser 并排）
- 授权 API Session（设置时间限制 + 次数限制）

## 3. API Mode 演示（60s）
- AI 查余额："帮我查一下钱包余额"
- AI 转账："转 0.01 SUI 给 xxx"
- AI Swap："用 0.5 SUI 换 WAL"（Cetus Aggregator）
- AI Walrus 存证："把这笔交易存到 Walrus"
- 全程展示：Session 签名计数递增、弹窗授权流程
- 重点：AI 发起请求 → MiaoWallet 验证 Session → Keychain 签名 → 返回结果，私钥全程不离开本机

## 4. Browser Mode 演示（45s）
- 授权 Browser Session
- AI 打开 DApp 网页（通过 Browser Relay）
- AI 操控浏览器：点击按钮、填写表单
- Chrome Extension 弹出签名请求
- 展示 AI 自动完成 DApp 交互全流程

## 5. 安全特性展示（25s）
- Session 机制：时间限制 + 次数限制，到期自动失效
- 撤销演示：撤销 Session 后 AI 立即无法签名
- 私钥保护：
  - Keychain 加密存储（macOS 系统级安全）
  - 私钥不上传到 AI 服务器
  - AI 读取需要用户弹窗授权
- Keeper Bot 加密方案：PBKDF2 + Fernet 加密，密码解锁，内存注入
- Walrus 存证：链上交易记录不可篡改，AI 行为可审计

## 6. 收尾（15s）
- 回到 Walrus Sites 展示页
- 展示 GitHub 仓库 + 项目结构
- 总结："MiaoWallet 解决了 AI Agent 操作钱包的信任问题——给 AI 能力，但不给私钥"

---

## 演示前准备清单
- [ ] testnet 钱包有足够 SUI（≥5 SUI）
- [ ] WebGUI 正常运行（python3 miaowallet_webgui.py）
- [ ] sui_bridge.py 运行中（端口 3847）
- [ ] Chrome Extension 已安装（Sui Agent Wallet）
- [ ] Browser Relay 已连接
- [ ] Walrus Sites 可访问
- [ ] 录屏软件就绪

## 亮点总结
1. **安全中间层**：AI 能操作钱包但碰不到私钥
2. **双模式**：API（MCP）+ Browser（Chrome Extension）独立授权
3. **Session 机制**：时间/次数限制 + 随时撤销
4. **Walrus 存证**：链上审计 AI 行为，呼应 Track 1 要求
5. **全栈跑通**：transfer、swap、attestation 全部真实上链
6. **去中心化部署**：展示页托管在 Walrus Sites

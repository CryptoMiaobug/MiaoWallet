# MiaoWallet - SUI 钱包管理

## 配置要求

**重要**：要使 `/miaowallet` 命令正常工作，需要在 `openclaw.json` 中添加 Telegram 自定义命令：

```json
"channels": {
  "telegram": {
    "enabled": true,
    // ... 其他配置
    "customCommands": [
      { "command": "miaowallet", "description": "打开钱包面板" }
    ]
  }
}
```

**多 Bot 用户注意**：如果你运行多个 OpenClaw 实例，需要为每个 bot 单独配置并重启 gateway。

## 快捷指令

| 指令 | 操作 |
|------|------|
| `/miaowallet` | 打开钱包面板（列出钱包、余额等） |
| `转 X SUI 给 <地址>` | 转账流程（先预览再确认） |

## /miaowallet 钱包面板

当用户发送 `/miaowallet` 时，打开独立的钱包面板窗口：

```bash
open <SKILL_DIR>/miaowallet.command
```

这会在 macOS 上弹出一个终端窗口，显示交互式钱包管理菜单。

### 终端窗口功能
1. **列出钱包** - 显示所有钱包和地址
2. **添加钱包** - 添加新的 SUI 钱包（需要私钥）
3. **删除钱包** - 从系统中移除钱包
4. **测试钱包** - 测试钱包与 SUI 网络的连接
5. **重置授权** - 重置钱包的 ACL 权限
6. **导出配置** - 导出钱包配置（不含私钥）
7. **切换语言** - 中英文切换
8. **快速转账** - 直接在面板中完成 SUI 转账

## 转账流程

### 第一步：Dry Run 预览（不需要 Keychain）

```bash
cd <SKILL_DIR> && source venv/bin/activate
python3 sui_transfer.py sui1 <收款地址或.sui域名> <金额> --dry-run
```

将预览结果展示给用户，包括：
- 资产变化（发送方 / 收款方）
- Gas 预估
- 总支出

### 第二步：等用户确认

用户说"确认"后才执行下一步。

### 第三步：执行转账（需要 Keychain）

```bash
python3 sui_transfer.py sui1 <收款地址或.sui域名> <金额> --yes
```

### 重要事项
- **钱包别名**: `sui1`
- **私钥**: 存储在 macOS Keychain (service: openclaw_bot)
- **不要用 sui CLI 转账** — 它的 keystore 里的地址没余额
- 支持 `.sui` 域名自动解析
- `--dry-run` 不需要私钥，只做模拟
- `--yes` 跳过交互确认

# crypto-project-tracker · Hermes Agent 版

个人加密项目信息追踪工具，面向 [Hermes Agent](https://github.com/nousresearch/hermes-agent)。本项目由 [jamesxxx-ai/crypto-project-tracker](https://github.com/jamesxxx-ai/crypto-project-tracker)（审计基线 `666e3ce`）改造而来：

- 保留原项目的信息追踪能力：OpenNews / OpenTwitter、KOL、项目团队、行情、提醒、事件聚合。
- 去掉 Web 界面与公网部署，改为「独立采集器 + MCP 工具 + Skill + Cron」。
- 修复了安全审计中发现的问题，详见 [docs/SECURITY-AUDIT.zh-CN.md](docs/SECURITY-AUDIT.zh-CN.md)。

## 架构

```
Hermes Agent（CLI / Telegram 等网关）
 ├─ Skill  crypto-project-tracker          hermes/skills/
 ├─ MCP    crypto_tracker（stdio）          python -m crypto_tracker.mcp_server
 │    只读 store；写操作投递到 spool；不持有 Token，不联网
 └─ Cron   tracker-alerts.py（no-agent，每 5 分钟推送新提醒）+ 每日简报（agent + skill）

采集器 crypto-tracker-collector（systemd，独立用户，不监听端口）
 持有 OPENNEWS_TOKEN（systemd 加密凭证），是 store 的唯一写入者
 采集频率：行情 60s · 新闻 / 社交 30min · 情报 5min · 提醒评估 20s · RootData 24h
```

目录说明：

| 目录 | 内容 |
|---|---|
| `src/crypto_tracker/` | 采集器、MCP 服务、核心规则 |
| `hermes/` | Skill、配置片段、提醒脚本 |
| `deploy/systemd/` | 加固的服务单元、安装脚本 |
| `tests/` | 单元测试与端到端测试 |

## 快速开始

VPS 部署步骤见 [docs/HERMES-SETUP.zh-CN.md](docs/HERMES-SETUP.zh-CN.md)。本地开发：

```bash
uv sync --frozen                                   # 唯一第三方依赖：mcp==2.2.0（锁定哈希）
uv run python -m unittest discover -s tests -t .   # 全部测试
OPENNEWS_TOKEN_FILE=~/.config/crypto-tracker/token TRACKER_HOME=/tmp/ct \
  uv run python -m crypto_tracker.collector --once # 采集一轮（Token 文件须为 0600）
TRACKER_HOME=/tmp/ct uv run python -m crypto_tracker.mcp_server   # stdio MCP
```

## 能力

| 能力 | MCP 工具 | 数据来源 |
|---|---|---|
| 项目概览 | `tracker_project_brief` | 汇总下列各项 |
| 新闻 / 官方 X / 官网 / RSS | `tracker_events`、`tracker_event_detail` | OpenNews、OpenTwitter、官网、用户确认的 RSS |
| 团队 | `tracker_team` | RootData 公开团队区与人工证据；只收录明确提及项目的推文 |
| KOL / 近期讨论者 | `tracker_kol` | 近 7 天提及官方账号、粉丝 ≥ 2 万 |
| 观点日志 | `tracker_viewpoints` | 按明确第一人称措辞归类，未推断真实仓位 |
| 行情 | `tracker_market` | Binance USDⓈ-M 永续公共接口：4h 收盘 EMA200/360、1h OI |
| 信号 | `tracker_signals` | OpenNews 的交易所公告、资金费率、大额清算、资金动态、OI |
| 宏观日历 | `tracker_macro_calendar` | 供应方日历（可能不可用） |
| 提醒 | `tracker_alerts`、`tracker_upsert_alert_rule` | 价格、OI、价位、EMA、组合、新闻、公告、费率、清算、资金动态 |
| 摘要 | `tracker_digest` | 昨日原文要点，每个项目最多 3 条 |

所有写操作都需要 Hermes 审批，由采集器用原有校验逻辑执行。完整工具说明见 [hermes/skills/crypto-project-tracker/references/tools.md](hermes/skills/crypto-project-tracker/references/tools.md)。

## 数据边界（沿用原项目的说明）

- **覆盖范围。** 数据来自抽样检索，不代表全网覆盖。每轮信号查询最多取 100 条，达到上限时会标注；同一事件的归并规则偏保守，也不做独立事实核验。
- **公告分类。** 交易所公告区分上币、下架、充提、合约调整和其他。普通评论不会被归为上币，「其他公告」不触发专门的公告提醒。
- **资金费率。** 保留原文单位、交易所和观察周期，不换算年化，也不承诺套利收益。资金费率提醒依据供应方的事件，不是自定义的费率数值扫描。
- **大额清算。** 金额单位为 USD，只使用原文明确标注的清算金额，并且不会把可能重叠的金额相加。阈值为正数时，未知金额的记录不会触发。
- **资金动态与 OI。** 这些只是事件线索，不能证明钱包归属，也不等于完整的持仓监控。消息与行情时间接近不代表因果关系。
- **提醒规则。** 只对规则创建之后的新事件生效，采用收盘确认，受冷却时间和去重限制。提醒是规则命中，不是投资建议。
- **身份标注。** 团队身份标注为「非实时任职核验」，KOL 身份未经核实。
- **翻译与交易。** 不做机器翻译，由 Agent 按需翻译；不执行任何交易，也不接触交易所私钥。

## 安全要点

- **不监听端口。** 采集器和 MCP 服务都不开任何端口，VPS 只需开放 SSH。
- **Token 隔离。** Token 只在采集器进程中：systemd `LoadCredentialEncrypted` 负责解密；带 Token 的请求禁止重定向，并有主机白名单。
- **最小权限。** Hermes 用户只能读 store、向 spool 投递命令，读不到凭证。
- **防提示注入。** 第三方文本会被清理和截断，并标记 `untrusted_content`；Skill 规定这类内容只能当数据看待。
- **依赖锁定。** 依赖锁定并校验哈希（`uv.lock`、`deploy/requirements.lock.txt`）。CI 运行测试、ruff、gitleaks 和隐藏字符检查。

## 许可证

MIT。第三方数据、商标和 API 权限按各服务方条款使用。回到原 Web 阅读器：`git checkout 666e3ce`。

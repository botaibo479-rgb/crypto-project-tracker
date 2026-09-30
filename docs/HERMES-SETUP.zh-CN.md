# VPS 部署：采集器 + Hermes Agent

本文假设 Hermes Agent 与采集器部署在同一台 Linux VPS 上（需要 systemd ≥ 250），Hermes 以普通用户（下文记为 `hermes`）运行。

## 0. 安全前提

- Hermes **不以 root 运行**，且 `hermes` 用户没有免密 sudo。否则同机上的任何隔离都形同虚设。
- 防火墙只放行 SSH 入站，SSH 只允许密钥登录。采集器和 MCP 服务都不监听端口；Hermes 网关（如 Telegram）使用出站连接。
- 建议把 Hermes 的终端后端设为 docker（`terminal.backend: docker`），让模型生成的命令在容器中运行。
- 不要安装以 curl 调用 API 的 opennews / opentwitter skill，也不要把 Token 加进 `terminal.env_passthrough`（见审计 S6）。

## 1. 安装

```bash
git clone <本仓库> /root/src/crypto-project-tracker
cd /root/src/crypto-project-tracker
git checkout <已审阅的提交 SHA>
sudo HERMES_USER=hermes PYTHON=python3.12 deploy/systemd/install.sh
```

脚本会完成以下工作：

- 创建系统用户 `crypto-tracker` 和组 `tracker-readers`，并把 `hermes` 加入该组。
- 把代码复制到 `/opt/crypto-tracker/releases/<提交>`，归 root 所有、只读；`current` 软链接指向这个版本。
- 按 `uv.lock` 安装依赖（有 uv 时用 `uv sync --frozen`，否则用 `pip --require-hashes`）。
- 建立目录：`/var/lib/crypto-tracker/store`（2750，只有采集器能写）和 `/var/lib/crypto-tracker/spool`（2770，组内可写，用来投递命令）。

## 2. 存入凭证（只在采集器中）

```bash
sudo systemd-ask-password -n "OpenNews token:" \
  | sudo systemd-creds encrypt --name=opennews_token - /etc/credstore.encrypted/opennews_token
# 可选：DefiLlama Pro key（融资披露）
sudo systemd-ask-password -n "DefiLlama key:" \
  | sudo systemd-creds encrypt --name=defillama_key - /etc/credstore.encrypted/defillama_key
# 然后取消服务单元中 defillama_key 那一行的注释
```

- **获取 Token。** 在浏览器地址栏手动输入 `https://app.newsliquid.com/mcp` 获取自己的 Token，不要使用他人分享的带邀请码链接。
- **加密存放。** `systemd-creds` 用主机密钥（有 TPM 时同时绑定 TPM）加密；运行时只有这个服务能在 `$CREDENTIALS_DIRECTORY` 中读到明文。
- **最小权限。** 如果服务商支持，给采集器单独签发一个 Token，并选用够用的最低套餐。
- **读取顺序。** 程序依次查找：systemd 凭证 → `OPENNEWS_TOKEN_FILE`（必须是 0600）→ 环境变量 → 项目目录的 `.env.local`（仅供开发）。

## 3. 启动采集器

```bash
sudo systemctl enable --now crypto-tracker-collector
journalctl -u crypto-tracker-collector -f     # 日志只显示 Token 的指纹，不显示明文
sudo systemd-analyze security crypto-tracker-collector
```

从原 Web 阅读器迁移数据时，只复制已知文件，不会修改原目录：

```bash
sudo -u crypto-tracker env PYTHONPATH=/opt/crypto-tracker/current/src TRACKER_HOME=/var/lib/crypto-tracker \
  /opt/crypto-tracker/current/.venv/bin/python -m crypto_tracker.cli migrate --from /path/to/old/data
```

## 4. 接入 Hermes（以 hermes 用户操作）

先重新登录，让新的用户组生效。然后：

```bash
# 1) 把 hermes/config.snippet.yaml 中的 mcp_servers.crypto_tracker 合并进 ~/.hermes/config.yaml
# 2) 安装 skill 和提醒脚本
cp -r /opt/crypto-tracker/current/hermes/skills/crypto-project-tracker ~/.hermes/skills/
install -m 0700 /opt/crypto-tracker/current/hermes/scripts/tracker-alerts.py ~/.hermes/scripts/
# 3) 在 Hermes 对话中执行 /reload-mcp，确认出现 mcp__crypto_tracker__* 工具
```

关键配置如下（完整内容见 `hermes/config.snippet.yaml`）：

```yaml
mcp_servers:
  crypto_tracker:
    command: "/opt/crypto-tracker/current/.venv/bin/python"
    args: ["-m", "crypto_tracker.mcp_server"]
    env:
      PYTHONPATH: "/opt/crypto-tracker/current/src"
      TRACKER_HOME: "/var/lib/crypto-tracker"
    trust: untrusted          # 写工具每次调用都需要审批
    tools: { resources: false, prompts: false }
```

## 5. 定时任务

先以暂停状态创建，手动运行一次核对输出后再启用：

```bash
hermes cron create "every 5m" --no-agent --script tracker-alerts.py \
  --deliver telegram --name crypto-tracker-alerts --paused
hermes cron create "45 8 * * *" \
  "按 crypto-project-tracker skill 的「每日简报」流程生成今天的项目简报" \
  --skill crypto-project-tracker --deliver telegram --name crypto-tracker-daily --paused
hermes cron run <job_id>
hermes cron resume <job_id>
```

- **提醒脚本不消耗 LLM。** 没有新提醒时不发送任何消息；第一次运行只记录起点，不补发历史提醒。
- **故障可见。** 采集器超过 15 分钟没有更新时，每 6 小时发送一次告警；脚本出错时 Hermes 会把错误推送出来。
- **观点变化。** 只有在项目页开启了观点变化记录（`tracker_viewpoint_alerts`）后才会推送。

## 6. 验收清单

- [ ] 用 hermes 用户执行 `cat /etc/credstore.encrypted/opennews_token` 和 `systemctl show -p Environment crypto-tracker-collector`，都拿不到 Token 明文。
- [ ] `systemd-analyze security crypto-tracker-collector` 显示较低的暴露评分。
- [ ] 用 hermes 用户向 `/var/lib/crypto-tracker/store/` 写文件，应被拒绝；写操作只能经 MCP 工具进入 spool。
- [ ] `ss -ltnp` 中没有采集器或 MCP 进程在监听。
- [ ] 采集器的出站连接只指向 `ai.6551.io`、`fapi.binance.com`、`api.coingecko.com`、`rootdata.com`、官网、你添加的 RSS 主机，以及可选的 `pro-api.llama.fi`（可用 `ss -tnp` 或出站防火墙日志核对）。
- [ ] `grep -r "<Token 前 8 位>" /var/lib/crypto-tracker ~hermes/.hermes/logs ~hermes/.hermes/cron` 没有结果。
- [ ] 在 Hermes 中询问「NEAR 最近 24 小时有什么动态」，回答引用了带 url 的条目，并说明了数据边界。
- [ ] 通过对话新建一条测试提醒（Hermes 会弹出审批），`tracker_alerts` 能看到它；随后删除。

## 7. 升级与回滚

```bash
cd /root/src/crypto-project-tracker && git fetch && git checkout <新的已审阅提交>
sudo HERMES_USER=hermes deploy/systemd/install.sh            # 生成新的 release 并切换 current
sudo systemctl restart crypto-tracker-collector                # 然后在 Hermes 中执行 /reload-mcp
```

回滚有以下几种方式：

- **回退代码。** 执行 `sudo ln -sfn /opt/crypto-tracker/releases/<旧提交> /opt/crypto-tracker/current`，再 `systemctl restart crypto-tracker-collector`，最后在 Hermes 中 `/reload-mcp`。
- **只停用 Hermes 集成。** 在 `mcp_servers.crypto_tracker` 下设置 `enabled: false` 后 `/reload-mcp`；定时任务用 `hermes cron pause <job_id>` 暂停，或用 `hermes pause` 全部暂停。
- **停止采集。** 执行 `systemctl disable --now crypto-tracker-collector`。
- **恢复数据。** 升级前先备份：`sudo env PYTHONPATH=/opt/crypto-tracker/current/src TRACKER_HOME=/var/lib/crypto-tracker /opt/crypto-tracker/current/.venv/bin/python -m crypto_tracker.cli backup /root/backup/tracker-$(date +%F)`，生成 store 的 tar.gz；恢复时停服解压即可。
- **回到原 Web 阅读器。** 执行 `git checkout 666e3ce`，数据仍使用原 `data/` 目录。

## 8. 凭证轮换与事故处理

1. 在服务商页面吊销旧 Token，签发新 Token。
2. 重新执行第 2 步的 `systemd-creds encrypt`，再 `systemctl restart crypto-tracker-collector`。
3. 用旧 Token 的前几位在 `/var/lib/crypto-tracker`、journal 和 `~/.hermes` 中 grep，确认没有残留。
4. 如果 Token 曾经出现在对话、日志或 Git 中，视为已泄露：立即吊销，并检查服务商的调用记录。

## 9. 故障排查

| 现象 | 处理 |
|---|---|
| 工具返回 `collector.stale=true` | 执行 `systemctl status crypto-tracker-collector`，并查看 journal |
| 写操作一直 `queued` | 检查采集器是否在运行；检查 spool 目录权限（2770，组 tracker-readers）；确认 hermes 已重新登录 |
| `opennews_credential=missing` | 凭证未加载：检查服务单元中的 `LoadCredentialEncrypted` 和凭证文件路径 |
| 行情 `HTTP 403 / 451` | Binance 限制了这台 VPS 所在的地区，需要更换机房或关闭行情提醒 |
| 官网或 RSS 报「合成 DNS 地址」 | 本机使用了 fake-ip 代理：修正 DNS，或显式设置 `TRACKER_ALLOW_DOH=1`（会向 dns.google 暴露所查询的域名） |

# 安全审计报告：crypto-project-tracker

- **审计对象**：`jamesxxx-ai/crypto-project-tracker`，分支 `codex/open-source`，提交 `666e3ce`（2026-09-30）。
- **审计基线**：本 fork 的改造从 `666e3ce` 开始。回滚到原 Web 阅读器时，检出该提交后运行 `python3 run.py` 即可。
- **审计范围**：全部 Python 后端、`dist/` 前端、部署文件（Dockerfile、compose、Caddy）和文档中的链接；另外审阅了教程推荐安装的 `6551Team/opennews-mcp`、`6551Team/opentwitter-mcp`。
- **方法**：逐文件人工阅读；grep 危险调用（`eval`、`exec`、`subprocess`、`pickle`、`base64`、动态导入、`socket`）；汇总所有外联主机；比对内置第三方库的哈希；运行原有单元测试（113 个，全部通过）。

## 结论

**没有发现恶意代码、后门、硬编码凭证或隐藏外联。**

- 所有外联主机都能对应到具体功能。
- `dist/lightweight-charts.js` 与 npm `lightweight-charts@5.2.1` 包内的 `dist/lightweight-charts.standalone.production.js` 逐字节一致，sha256 为 `e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf`。
- 前端统一用 `escapeHtml` 转义，外链经 `safeUrl` 只放行 https。
- POST 请求校验 Host、Origin、Content-Type；默认只监听 127.0.0.1。

下表列出的是设计缺陷，以及改造成 Hermes Agent 工具后才会出现的新风险。

## 外联主机清单（原版）

| 主机 | 用途 | 是否带凭证 |
|---|---|---|
| `ai.6551.io` | OpenNews / OpenTwitter API | 是，Bearer `OPENNEWS_TOKEN` |
| `fapi.binance.com` | 公共行情：ticker、K 线、OI | 否 |
| `api.coingecko.com` | 项目搜索与资料 | 否 |
| `www.rootdata.com` / `tw.rootdata.com` | 公开团队区和人物页 | 否 |
| `api.official-admin.soo.network`、`www.near.org`、`nillion.com`、`phala.com` | 四个默认项目的官网文章 | 否 |
| 用户添加的 RSS / Atom 主机 | 免费订阅源 | 否 |
| `pro-api.llama.fi` | DefiLlama 融资数据（可选） | 是，key 在 URL 路径里 |
| `translate.googleapis.com` | 非官方翻译接口 `client=gtx` | 否，但会发送新闻原文 |
| `dns.google` | 遇到合成 DNS 地址时的 DoH 回退 | 否，但会发送查询的域名 |
| `ntfy.sh` | 可选推送 | 可选 Bearer |
| `fonts.googleapis.com`、`pbs.twimg.com` | 浏览器端字体和头像 | 否 |

## 问题清单

| # | 等级 | 问题 | 位置（`666e3ce`） | 处置 |
|---|---|---|---|---|
| S1 | **中高** | **Bearer Token 会随 HTTP 重定向转发。** `request()` 用的是 urllib 默认的重定向处理器，CPython 的 `HTTPRedirectHandler.redirect_request` 只去掉 `content-length` 和 `content-type`，所以 `Authorization` 会被带到任意新主机，https→http 降级时也照样发送。ai.6551.io 一旦被劫持或配置出错，Token 就会泄露。 | `server.py` 中的 `request()`；调用点在 `provider_news`、`team_news.collect`、`features.enrich_avatars` / `discover`、`intelligence.Store.collect` | 带 Token 的请求改用专用 opener：禁止重定向，只允许 https，主机白名单只有 `ai.6551.io` |
| S2 | 中 | 通用 `request()` 没有主机白名单，也不校验重定向目标。RootData 和官网抓取只校验首跳，之后的跳转会被跟随，理论上可以跳到内网或云元数据地址（SSRF）。 | `server.request`、`rootdata_monitor.validate_source` / `refresh` / `resolve_candidates`、`server.public_news` | 公网抓取统一改走已有的 `public_sources.fetch`（固定公网 IP、逐跳校验）；Binance 和 CoinGecko 各用主机白名单客户端 |
| S3 | 中 | 文档里有**带邀请码的推广链接**（`?code=PC9PTKVS`），并推荐付费套餐。域名本身可信：6551 官方 MCP 仓库也指向 `app.newsliquid.com/mcp` 和 `6551.io/mcp`，所以不是钓鱼，但属于商业返佣。 | `README.md`、`TUTORIAL.zh-CN.md` | 删除邀请码，只保留官方凭证页，并提示手动输入 https 地址 |
| S4 | 中 | **公网暴露面。** compose 对外开放 80/443，只有 Caddy basic_auth 一道防线（单口令，没有限流或 2FA）。Token 通过容器环境变量传入，`docker inspect` 能看到。镜像没有固定 digest。应用本身不做鉴权，本机其他进程可以直接读数据、改规则，Origin 校验只挡得住浏览器。 | `compose.yaml`、`Dockerfile`、`deploy/`、`runtime_config.py` | Hermes 方案不再提供 HTTP 服务，这些问题随之消失；删除相关文件 |
| S5 | 中（新增） | **Prompt 注入。** 推文、新闻、RSS、RootData 的文本会进入 LLM 上下文，其中可能夹带指令。 | 所有采集文本 | MCP 输出结构化并截断，标注 `untrusted_content`；在 Skill 中写明防护规则；MCP 配置 `trust: untrusted`，写操作需要审批 |
| S6 | 中（新增） | **上游 curl 型 skill 会把 Token 暴露给 shell。** `npx skills add 6551Team/...` 安装的 SKILL.md 通过 curl 调用 `$OPENNEWS_TOKEN`，在 Hermes 里只能把 Token 加进 `terminal.env_passthrough`，这样 LLM 生成的命令都能读到它。`npx skills` 本身也没有锁版本。 | `README.md`、`TUTORIAL.zh-CN.md` | 不安装这两个 skill，改用 MCP 通道 |
| S7 | 低 | **数据外泄给第三方。** 新闻和推文原文会发到非官方的 Google 翻译接口，等于暴露关注列表；DoH 回退会把域名查询发给 `dns.google`；ntfy.sh 是公共服务器，主题名就是口令；前端还会加载 Google Fonts。 | `features.translate_one`、`public_sources.PublicHTTPS.connect`、`delivery.py`、`dist/style.css` | 删除翻译（改由 LLM 按需翻译）；DoH 改为显式开启；删除 ntfy（改由 Hermes 推送）；删除 UI |
| S8 | 低 | `SIGNAL_ENV_FILE` 可以读取任意路径的文件，解析方式也很简陋。 | `server.py` 顶部 | 删除，改用 `secrets.py` |
| S9 | 低 | Phala 的 atom.xml 直接交给 `ET.fromstring` 解析，没有拦截 DOCTYPE/ENTITY。 | `server.public_news` | 统一使用 `parse_feed` |
| S10 | 低（改造必修） | 代码会向 stdout 打印；在 MCP stdio 模式下，stdout 就是 JSON-RPC 通道。另外有大量 `except Exception: pass` 直接吞掉错误。 | `server.py` 中的各个 loop | 改用 logging 输出到 stderr，并加脱敏 filter |
| S11 | 低 | SOON、NEAR、NIL、PHA 四个项目各有硬编码的官网抓取代码，其中 SOON 走的 `official-admin` 接口需要人工确认。 | `server.public_news` | 移入可选的 `official_sites` 适配器 |
| S12 | 低 | `rootdata-team.json` 是 20 条人工整理的团队身份快照（2026-09-27 核对）；如果 RootData 本身出错，冒名账号可能被当成团队成员。 | `rootdata-team.json` | 保留「非实时任职核验」标签，并定期复核 |
| S13 | 低 | 代码写成分号串接的单行，难以审计。 | 全仓库 | 单独提交一次纯格式化 |
| S14 | 信息 | 上游 MCP 的依赖写成 `mcp>=1.25`、`httpx>=0.27`，没有锁版本。 | 上游 `pyproject.toml` | 本项目依赖锁定精确版本 |
| S15 | 信息 | `data/*.json` 明文保存关注列表、阅读记录和规则（不含密钥），已在 `.gitignore` 中排除。 | — | 新数据目录权限设为 0750/0640 |

## 链接核查

文档和前端里的外链只指向以下域名：`python.org`、`nodejs.org`、`npmjs.com`、`skills.sh`、`github.com/6551Team`、`docs.ntfy.sh`、`x.com`、`tradingview.com`、`binance.com`、`rootdata.com`、`newsliquid.com`。没有发现仿冒域名或短链跳转。

## 上游 6551 MCP 服务（教程推荐安装）

- `opennews-mcp`（`e329f36`）和 `opentwitter-mcp`（`8d69ca5`）都是 Python MCP 服务，从环境变量 `OPENNEWS_TOKEN` 或项目根目录的 `config.json` 读取 Token。**不要把 Token 写进 `config.json`**，容易被误提交。
- httpx 默认不跟随重定向，这一点没有问题。
- `opentwitter-mcp` 的 `add_twitter_watch` 和 `delete_twitter_watch` 会改写服务端的监控列表。接入 Hermes 时应在 `tools.include` 中排除这两个工具，并设置 `trust: untrusted`。
- `opentwitter-mcp` 的错误提示里写的凭证页地址是 `http://` 开头，请手动改用 https。

## 整改对应关系

| 阶段 | 内容 |
|---|---|
| 1 | 纯格式化（S13） |
| 2 | S1、S2、S3、S6、S7、S8、S9 |
| 3 | 重构为 `crypto_tracker` 包和独立采集器：S10、S11，凭证加载与脱敏 |
| 4 | MCP 服务：S5 |
| 5–7 | Hermes Skill 与 Cron；删除 Web 和公网部署（S4）；systemd 加固部署；CI 与 secret 扫描 |

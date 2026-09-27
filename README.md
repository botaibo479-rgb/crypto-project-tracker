# Signal · 个人加密项目信息追踪工具

本地运行的中文新闻阅读器，聚合项目官方资讯、团队 X、近期讨论者和市场信号。默认 SOON、NEAR、PHA、NIL 四个示例。

**[完整教程 · 手把手教你如何搭建个人的加密项目信息追踪工具](TUTORIAL.zh-CN.md)**

## 快速开始

需要 Python 3.12+，无需 pip 依赖。下载解压后，在项目目录运行。

```bash
python3 configure.py
python3 run.py
```

Windows 使用 `py -3` 替换 `python3`。打开 http://127.0.0.1:4317/ ，终端保持运行，Ctrl+C 停止。未配置 Token 时可检查页面与公开行情，但认证来源不可用。

## 注册与 skills

[NewsLiquid 注册入口（邀请码 PC9PTKVS）](https://app.newsliquid.com?code=PC9PTKVS) · [MCP 凭证页面](https://app.newsliquid.com/mcp)

在支持的 AI 助手环境安装两个 skills，需要 Node.js/npx。

```bash
npx skills add 6551Team/opennews-mcp
npx skills add 6551Team/opentwitter-mcp
```

两项服务使用 `OPENNEWS_TOKEN`。阅读器直接调用 API，skills 供 AI 助手调用。额度和权限以服务商当前页面为准。

## 功能与范围

- 自定义项目、Logo、分组、排序、未读和收藏。
- 中文优先、原文切换、官方/团队来源区分、规则式事件合并。
- RootData 公开团队区及人物页关联，讨论者至少 20,000 粉丝。
- K 线、EMA 200/360、新闻标记，价格/OI/价位/均线站内提醒。
- 失败保留旧结果并显示时间，数据保存于本地 data/。

本地单人使用，无交易执行。翻译可能限流或错误；团队发现依赖公开页及手动关联；新闻覆盖和事件归并非完整或独立事实核验。浏览器通知需主动授权并保持页面可运行，不是离线推送。Windows 与操作系统通知尚未完成真机验收。

## 数据与安全

只将 Token 配到 `.env.local` 或环境变量，不提交到 Git。后台仅向 ai.6551.io 发送该 Token。公开新闻翻译调用 Google 翻译端点，搜索使用 CoinGecko，行情使用 Binance，团队资料读取 RootData；头像和字体可能产生浏览器外部请求。

默认监听 127.0.0.1，请勿直接暴露到公网。源码不含用户凭证、data/ 或原开发环境配置。备份、限制与故障排查见教程。

## 验证与贡献

```bash
python3 -m unittest discover -q
node --test test_*.cjs
```

提交问题时移除日志中的 Token、个人路径与阅读数据。欢迎提交复现步骤和改进测试。源码采用 [MIT](LICENSE)，第三方数据与商标按各自权限使用。上游 skills 未打包，分别从原作者仓库安装。

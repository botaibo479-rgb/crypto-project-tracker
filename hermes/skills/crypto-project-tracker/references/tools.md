# crypto_tracker MCP 工具参考

由 `crypto_tracker.mcp_server.tools` 的工具定义生成。Hermes 中的名称为 `mcp__crypto_tracker__<工具名>`。

- **只读**：带 readOnlyHint，不改变任何状态；只读取采集器数据。
- **查询（经采集器）**：只读，但由采集器联网查询 CoinGecko。
- **写**：没有 readOnlyHint，在 `trust: untrusted` 下每次调用都需要用户批准；命令进入 spool，由采集器校验后执行。

## `tracker_list_projects` — 只读

List watched projects with ids, symbols, official X accounts, websites and team size.

## `tracker_project_brief` — 只读

One-call overview of a project: market snapshot, top events, official/team posts, KOL discussants, OpenNews signals, fired alerts and source health for the last `hours` (1-168). `project` accepts id, symbol or name.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `hours` | integer | 否 | 24 |

## `tracker_events` — 只读

Curated, de-duplicated events (news, official X, team X, RSS, official sites), newest and most important first. Filter by project, channel, topic text, quality score (0-100) and time window (hours, max 720).

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string / null | 否 | null |
| `since_hours` | integer | 否 | 24 |
| `channel` | opennews / x / team / subscription / official_site / null | 否 | null |
| `topic` | string / null | 否 | null |
| `min_quality` | integer | 否 | 0 |
| `important_only` | boolean | 否 | false |
| `include_low_information` | boolean | 否 | false |
| `limit` | integer | 否 | 20 |

## `tracker_event_detail` — 只读

Full record of one event: complete text, related reports, cluster reasoning and later progress candidates.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `event_id` | string | 是 | — |

## `tracker_market` — 只读

Latest Binance USD-M perpetual snapshot collected for a project: price, 24h change, volume, EMA200/360 on closed 4h candles with cross state, and 1h OI change.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |

## `tracker_kol` — 只读

Recent discussants of a project's official X account (last 7 days, at least 20,000 followers), ordered by sample persistence and content form. KOL identity is not verified.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |

## `tracker_viewpoints` — 只读

Source-backed opinion journal for a project: attention statistics, recent posts with conservative stance labels (explicit first-person wording only), stance changes, watched accounts and price tracking of events.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `limit` | integer | 否 | 20 |

## `tracker_team` — 只读

Team members linked to a project (with evidence and verification labels) and their recent posts that explicitly mention the project.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `days` | integer | 否 | 30 |

## `tracker_signals` — 只读

OpenNews classified signals: exchange announcements, funding-rate events, large liquidations, fund flows and short-term OI/price moves.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string / null | 否 | null |
| `kind` | listing / funding / liquidation / flow / oi / price / null | 否 | null |
| `since_hours` | integer | 否 | 24 |
| `limit` | integer | 否 | 20 |

## `tracker_macro_calendar` — 只读

High-importance macro events for about the next two weeks (provider data; may be unavailable).

## `tracker_alerts` — 只读

Alert rules and alerts fired in the window, each with its evidence.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `since_hours` | integer | 否 | 24 |
| `limit` | integer | 否 | 30 |

## `tracker_digest` — 只读

Daily digest (source excerpts, up to three per project) for `date` (YYYY-MM-DD, local day). Defaults to yesterday; computed live if the collector has not stored it.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `date` | string / null | 否 | null |

## `tracker_status` — 只读

Collector health: last write, per-collector timings and errors, per-project source status, RSS subscriptions and credential presence (never the value).

## `tracker_command_result` — 只读

Outcome of a previously queued write command.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `command_id` | string | 是 | — |

## `tracker_search_projects` — 查询（经采集器）

Search CoinGecko (via the collector) for a project to add; returns candidate coin ids, names, symbols and market-cap rank.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `query` | string | 是 | — |

## `tracker_prepare_project` — 查询（经采集器）

Fetch CoinGecko details (name, symbol, homepage, X account) for a coin id so the user can review them before tracker_add_project.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `coin_id` | string | 是 | — |

## `tracker_add_project` — 写

Add a project to the watchlist (max 20). Aliases, contract addresses and exclude terms refine news matching; rootdata_url (a RootData project page whose X link matches x_account) enables team discovery.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `name` | string | 是 | — |
| `symbol` | string | 是 | — |
| `x_account` | string | 否 | "" |
| `website` | string | 否 | "" |
| `coin_id` | string | 否 | "" |
| `aliases` | array / null | 否 | null |
| `contracts` | array / null | 否 | null |
| `exclude_terms` | array / null | 否 | null |
| `rootdata_url` | string | 否 | "" |

## `tracker_remove_project` — 写 · 破坏性

Stop tracking a project and drop its collected events.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |

## `tracker_add_team_member` — 写

Link an X account to a project's team. evidence_url (https) must document the role; the member is labelled unverified.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `x_account` | string | 是 | — |
| `evidence_url` | string | 是 | — |
| `role` | string | 否 | "团队成员" |

## `tracker_set_rootdata_source` — 写

Set the RootData project page used for team discovery. The page's X link must match the project's official X account.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `url` | string | 是 | — |

## `tracker_rss` — 写

Manage free RSS/Atom sources: add a feed url (GitHub, Medium, Mirror and Telegram links are converted), toggle a source by id, discover feeds from the project website, or set economy mode (skip paid keyword search while RSS is healthy).

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `action` | add / toggle / discover / economy | 是 | — |
| `url` | string | 否 | "" |
| `label` | string | 否 | "" |
| `source_id` | string | 否 | "" |
| `enabled` | boolean | 否 | true |

## `tracker_upsert_alert_rule` — 写

Create or update an alert rule (max 40). Types: price (|24h change| >= threshold %), oi (|1h OI change| >= threshold %), level (close crosses above threshold), ema200 / ema (close crosses EMA200 / both EMAs; period 1h/4h/1d), combo (EMA cross and 1h OI >= threshold %), news (important news), listing / funding / liquidation (threshold = min USD, 0 = any) / flow (OpenNews events). Closed-candle confirmation; alerts fire only for events after the rule is created.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `type` | price / oi / level / ema200 / ema / combo / news / listing / funding / liquidation / flow | 是 | — |
| `name` | string | 是 | — |
| `threshold` | number | 否 | 5 |
| `period` | 1h / 4h / 1d / 24h / event / null | 否 | null |
| `cooldown_minutes` | integer | 否 | 60 |
| `listing_scope` | all / listing | 否 | "all" |
| `enabled` | boolean | 否 | true |
| `rule_id` | string / null | 否 | null |

## `tracker_alert_rule_action` — 写 · 破坏性

Pause/resume (toggle) or delete an alert rule.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `rule_id` | string | 是 | — |
| `action` | toggle / delete | 是 | — |

## `tracker_watch_account` — 写

Add (or remove) an X account to the opinion journal for the given projects, regardless of follower count (max 20 accounts). Does not follow anyone on X.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `x_account` | string | 是 | — |
| `projects` | array | 是 | — |
| `note` | string | 否 | "" |
| `remove` | boolean | 否 | false |

## `tracker_viewpoint_alerts` — 写

Enable or disable stance-change records for a project's opinion journal.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `enabled` | boolean | 是 | — |

## `tracker_track_event` — 写

Start (or stop) tracking price change 1h/24h/7d after an event, from a fresh Binance price at the time of the request. Not a performance claim.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `event_id` | string | 是 | — |
| `stop` | boolean | 否 | false |

## `tracker_request_refresh` — 写

Ask the collector to re-collect one project (or all) now. Rate limited to once per 5 minutes per project; consumes provider quota.

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string / null | 否 | null |

## `tracker_set_calendar_mapping` — 写

Map a project to its DefiLlama protocol id so disclosed funding rounds are collected (requires the collector's DefiLlama key).

| 参数 | 类型 | 必填 | 默认 |
|---|---|---|---|
| `project` | string | 是 | — |
| `coingecko_slug` | string | 否 | "" |
| `defillama_protocol_id` | string | 否 | "" |

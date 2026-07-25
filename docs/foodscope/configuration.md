# FoodScope 配置指南

FoodScope 是 Horizon 的可选食品行业扩展。关闭 `foodscope.enabled` 时，原有
Horizon 工作流保持不变。

## 快速启动

```bash
cp data/config.foodscope.example.json data/config.json
cp .env.example .env
uv sync --extra dev
uv run python -m src.main --no-deliver
```

先在 `.env` 中填写 `OPENAI_API_KEY`，或把 `ai`、`ai_routes` 改成其他受支持
的模型提供商。JSON 只保存环境变量名，不应写入密钥本身。

## 核心字段

| 路径 | 作用 | 默认/限制 |
|---|---|---|
| `foodscope.enabled` | 切换 FoodScope 工作流 | `false` |
| `foodscope.profile` | 内置画像 ID | `balanced` |
| `foodscope.profile_path` | 自定义画像文件；设置后优先于 ID | `null` |
| `foodscope.source_packs` | 按顺序加载的来源包 ID | 官方、行业媒体、新品 |
| `foodscope.source_pack_dir` | 来源包目录 | `data/foodscope/source_packs` |
| `foodscope.profile_dir` | 内置画像目录 | `data/foodscope/profiles` |
| `foodscope.source_overrides` | 按来源 ID 覆盖字段 | `{}` |
| `schedule.timezone` | IANA 时区 | `Asia/Shanghai` |
| `schedule.cron` | 五段 cron 表达式 | `30 6 * * *` |
| `collection.lookback_hours` | 每次回看时长 | 1–720 小时 |
| `collection.minimum_sources_per_run` | 当日来源不足时补齐的目标数 | `20` |
| `collection.extended_rotation_days` | 扩展源轮换周期 | `2` 天 |
| `collection.discovery_rotation_days` | 发现源轮换周期 | `3` 天 |
| `collection.fallback_sources_per_run` | 首轮空/失败后的备用来源上限 | `5` |
| `delivery.target_minutes` | 目标完成时长，用于观测 | 正整数 |

`ai_routes.fast` 用于候选内容的快速分析，`ai_routes.analysis` 用于入选内容的
深度分析。两条路由都支持独立模型、并发数、超时和重试次数。可按实际合同
价格设置 `input_cost_per_million` 与 `output_cost_per_million`；两者必须同时
填写。未配置价格时 token 仍会统计，但成本显示为 `unknown`，不会误报为零。

来源层级决定抓取频率：`core` 每次运行，`extended` 和 `discovery` 分别按上述
周期稳定轮换。如果轮换后低于 `minimum_sources_per_run`，系统优先从扩展源、
再从发现源确定性补齐。首轮选中来源为空或失败时，再按稳定顺序执行一次有界
备用波次，数量不超过 `fallback_sources_per_run`。实际来源 ID、运行时启用
名册及来源配置指纹都会写入本次 manifest；恢复运行继续使用同一选择，来源
配置已经变化时拒绝恢复，避免历史日期被新来源污染。

## 用户调整抓取时间

计划时间完全由用户控制。例如每天北京时间 08:15：

```json
{
  "schedule": {
    "timezone": "Asia/Shanghai",
    "cron": "15 8 * * *"
  },
  "collection": {
    "lookback_hours": 36,
    "minimum_sources_per_run": 20,
    "extended_rotation_days": 2,
    "discovery_rotation_days": 3,
    "fallback_sources_per_run": 5
  }
}
```

调度器按 IANA 时区计算夏令时。临时运行还可用 `--hours`，或用包含明确时区
偏移的 `--since`、`--until` 指定精确窗口：

```bash
uv run python -m src.main --hours 12 --no-deliver
uv run python -m src.main \
  --since 2026-07-23T00:00:00+08:00 \
  --until 2026-07-24T06:00:00+08:00 \
  --no-deliver
```

`--hours` 不能与显式窗口同时使用；显式窗口必须成对出现，最大 720 小时。
显式 `until` 会传到 GDELT、Google News 和 FoodScope 来源适配器，并在本地
再次检查发布时间上界，因此可用于可重复的历史回放。

## 分发配置

归档默认生成 Markdown 和 HTML。其他渠道相互隔离，一个渠道失败不会阻断
其余渠道。

### 邮件

设置 `email.enabled=true`，配置 SMTP 地址、端口、发件地址和订阅者数据。
`email.password_env` 的值是环境变量名，例如 `EMAIL_PASSWORD`；实际密码只放
在 `.env`。若没有订阅者，邮件渠道会显示为 `disabled`。

### 飞书/Lark

设置 `webhook.enabled=true`、`webhook.platform="feishu"`，并把
`webhook.url_env` 设为 `FOODSCOPE_FEISHU_URL`。在 `.env` 中填写机器人
Webhook URL。FoodScope 使用 Card JSON 2.0，并在内容较长时自动拆卡。

### 微信公众号草稿

设置 `delivery.wechat.enabled=true`，再配置 `app_id_env`、
`app_secret_env`、永久封面素材 `thumb_media_id` 和作者名。默认环境变量为
`WECHAT_APP_ID`、`WECHAT_APP_SECRET`。

FoodScope 只创建公众号草稿，不自动群发。这样既便于人工复核，也避免把
“生成草稿”误解为“已对外发布”。

## 配置校验

启动、`--healthcheck` 和 MCP 的 `fs_validate_config` 都会执行 Pydantic
校验并加载选中的画像及来源包。常见错误包括：

- 画像没有完整包含八个主题、权重越界/非有限，或权重之和不是 `1.0`；
- 来源包 ID 与文件内 `id` 不一致；
- 自定义路径不存在或 JSON 格式错误；
- 启用 X 来源但未声明 `x_access_mode="official_api"`；
- 把真实密钥误写进配置，而不是环境变量；
- cron、时区或抓取窗口不合法。

修改配置后，建议先运行：

```bash
uv run python -m src.main --no-deliver
```

再开启外部分发。

## 进一步阅读

- [来源包](source-packs.md)
- [简报画像](profiles.md)
- [运行与恢复](operations.md)
- [贡献指南](contributing.md)

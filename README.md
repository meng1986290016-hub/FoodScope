# FoodScope Horizon — 食品行业情报雷达

FoodScope 是基于 [Horizon](https://github.com/Thysrael/Horizon) 构建的**可自托管食品行业情报扩展**。它在保留 Horizon 通用信息聚合能力的同时，为食品、饮料、配料、包装和餐饮领域增加了一整套采集、分析、去重、证据校验和简报分发的工作流。

> **核心设计原则**：所有配置公开可审计，所有密钥只通过环境变量注入，仓库内的 JSON 文件绝不包含真实 secret。

## 它能做什么

- **定向抓取** — 从法规机构、行业媒体、新品数据库、科研机构和多语言新闻中抓取食品相关信号
- **跨语言去重** — 把同一事件的中、英、日、韩等多语言报道合并为一条事实
- **结构化分析** — 用两条独立 AI 路由分别完成“快速筛选”和“深度分析”，输出可机读的食品情报字段
- **证据准入** — 法规、标准、召回、食品安全声称必须有官方证据；否则会被隔离并审计
- **画像驱动** — 内置 `balanced`、`market`、`new_products`、`rd`、`compliance` 五个简报画像，一键切换信息偏向
- **多频道分发** — 生成 Markdown/HTML 归档，并可投递到邮件、飞书/Lark、微信公众号草稿、通用 Webhook 和 MCP 客户端
- **可恢复运行** — 每个阶段原子落盘，支持断点续跑和重发

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
# 1. 安装依赖
uv sync --extra dev

# 2. 复制配置模板
cp data/config.foodscope.example.json data/config.json
cp .env.example .env

# 3. 在 .env 中至少填入一个 AI 密钥
#    OPENAI_API_KEY=sk-...

# 4. 首次只生成归档，不向外分发
uv run python -m src.main --no-deliver
```

运行完成后检查 `data/runs/<run_id>/brief.md` 和 `brief.html`。确认内容符合预期后，再移除 `--no-deliver` 启用正式分发。

## 核心概念

### 简报画像（Profiles）

画像决定同一批事实如何排序和取舍，不改变原始抓取结果。内置画像位于 `data/foodscope/profiles/`：

| 画像 | 适合谁 | 主要倾向 |
| --- | --- | --- |
| `balanced` | 管理层、综合情报读者 | 八类主题平衡，商业信息占比 ≥ 70% |
| `market` | 市场、品牌、战略团队 | 消费趋势、零售餐饮、公司动态 |
| `new_products` | 新品、品牌、创新团队 | 新品上市、产品创新、包装与消费信号 |
| `rd` | 研发、配方、技术团队 | 原料技术、加工包装、科研 |
| `compliance` | 法规、质量、合规团队 | 法规标准、召回与风险预警 |

切换画像：

```json
{
  "foodscope": {
    "profile": "new_products"
  }
}
```

也可以复制内置画像后自行调整权重，或使用 `foodscope.profile_path` 指向自定义文件。

### 来源包（Source Packs）

来源包是经过筛选的来源集合，位于 `data/foodscope/source_packs/`：

| 来源包 | 侧重点 |
| --- | --- |
| `official_evidence` | 法规、标准、食品安全与召回的一手证据 |
| `global_industry` | 全球食品行业媒体和企业动态 |
| `product_launches` | 新品、配方、品牌与上市信息 |
| `ingredients_rd` | 原料、科研与食品技术 |
| `packaging_processing` | 包装、标签、加工和制造 |
| `retail_foodservice` | 零售、餐饮和渠道 |
| `research_data` | 研究机构、市场与消费数据 |
| `japan` / `korea` / `southeast_asia` | 区域市场包 |
| `discovery_queries` | 多语言发现查询 |
| `x_watch` | 经筛选的 X 观察名单，默认全部关闭 |

配置示例：

```json
{
  "foodscope": {
    "source_packs": [
      "official_evidence",
      "global_industry",
      "product_launches"
    ]
  }
}
```

同一来源若出现在多个包中会自动按 ID 合并。使用 `source_overrides` 可以关闭或覆盖单个来源，而不必复制整个来源包。

### 证据等级与采集层级

- **证据等级**：`primary`（一手官方） > `industry`（行业媒体） > `discovery`（发现查询） > `weak_signal`
- **采集层级**：`core` 每次运行，`extended` 默认两天轮换，`discovery` 默认三天轮换

法规、召回、食品安全类内容若证据等级不足，会被拒绝入选并记录到隔离审计。

## 配置说明

`data/config.json` 是唯一权威非密钥配置。关键字段：

| 路径 | 作用 | 默认值 |
| --- | --- | --- |
| `foodscope.enabled` | 启用 FoodScope 工作流 | `false` |
| `foodscope.profile` | 当前画像 ID | `balanced` |
| `foodscope.source_packs` | 加载的来源包 | 见示例 |
| `ai_routes.fast` | 候选内容快速分析 | — |
| `ai_routes.analysis` | 入选内容深度分析 | — |
| `schedule.timezone` | IANA 时区 | `Asia/Shanghai` |
| `schedule.cron` | 五段 cron | `30 6 * * *` |
| `collection.lookback_hours` | 回看时长 | `30` |
| `collection.minimum_sources_per_run` | 当日来源目标数 | `20` |
| `delivery.target_minutes` | 目标完成时长 | `60` |
| `delivery.wechat.enabled` | 微信公众号草稿 | `false` |

两条 AI 路由都支持独立设置 `provider`、`model`、`concurrency`、`timeout_seconds`、`max_attempts` 和价格。未配置价格时仍会统计 token，但成本显示为 `unknown`。

详细说明见：

- [`docs/foodscope/configuration.md`](docs/foodscope/configuration.md)
- [`docs/foodscope/source-packs.md`](docs/foodscope/source-packs.md)
- [`docs/foodscope/profiles.md`](docs/foodscope/profiles.md)
- [`docs/foodscope/operations.md`](docs/foodscope/operations.md)

## 使用 Kimi（Moonshot）

FoodScope 已把 Kimi 列为原生 provider。在 `.env` 中写入：

```bash
KIMI_API_KEY=sk-your-kimi-key
```

然后在 `data/config.json` 中使用：

```json
{
  "ai_routes": {
    "fast": {
      "provider": "kimi",
      "model": "moonshot-v1-8k",
      "api_key_env": "KIMI_API_KEY",
      "languages": ["zh"]
    },
    "analysis": {
      "provider": "kimi",
      "model": "moonshot-v1-128k",
      "api_key_env": "KIMI_API_KEY",
      "languages": ["zh"]
    }
  }
}
```

Kimi 复用 OpenAI 兼容客户端，因此也支持自定义 `base_url`、温度回退和 token 统计。常见模型名：`moonshot-v1-8k`、`moonshot-v1-32k`、`moonshot-v1-128k`。

## 运行方式

```bash
# 手动运行，只归档不投递
uv run python -m src.main --no-deliver

# 临时回看过去 12 小时
uv run python -m src.main --hours 12 --no-deliver

# 精确时间窗（可重复回放）
uv run python -m src.main \
  --since 2026-07-23T00:00:00+08:00 \
  --until 2026-07-24T06:00:00+08:00 \
  --no-deliver

# 按配置持续调度
uv run python -m src.main --daemon

# 校验配置并检查最近一次运行是否逾期
uv run python -m src.main --healthcheck

# 手动运行但标记为 scheduled（用于健康检查验收）
uv run python -m src.main --scheduled --no-deliver

# 恢复最近一次未完成运行
uv run python -m src.main --resume latest

# 恢复并重新分发
uv run python -m src.main --resume RUN_ID --redeliver
```

守护进程使用非阻塞文件锁，重复启动会以退出码 75 结束，避免并发运行。

## 运行产物

每次运行保存在 `data/runs/<run_id>/`：

| 文件 | 含义 |
| --- | --- |
| `raw.json` | 原始候选 |
| `normalized.json` | 统一食品行业字段 |
| `scored.json` | AI 分类与评分 |
| `filtered.json` | 证据准入、去重和画像筛选 |
| `enriched.json` | 深度分析与隔离审计 |
| `facts.json` | 不可变事实快照 |
| `brief.md` / `brief.html` | 从同一事实快照渲染的成品 |
| `manifest.json` | 阶段、计数、来源指标、分发状态和哈希 |

## 交付渠道

- **本地归档**：`brief.md` / `brief.html`
- **邮件**：自托管 SMTP/IMAP newsletter
- **飞书/Lark**：Card JSON 2.0，长内容自动拆卡
- **微信公众号**：只创建草稿，不自动群发
- **通用 Webhook**：Slack、Discord、DingTalk 等
- **MCP**：通过 MCP resources 读取运行状态和简报

各渠道相互隔离，一个渠道失败不会阻断其余渠道。已经成功发送且事实哈希相同的渠道会标记为 `skipped`，防止重复发送。

## 开发与测试

```bash
# 运行全部测试
uv run pytest

# 类型检查
uv run mypy src/foodscope

# 代码风格检查
uv run ruff check src/foodscope tests/foodscope
```

当前测试套件包含 554 个用例，覆盖配置模型、来源适配器、情报流水线、去重、证据校验、画像选择、运行存储、恢复、分发和 MCP。

## 项目结构

```
src/
  foodscope/          # FoodScope 核心包
    models.py         # 食品情报数据模型
    config.py         # FoodScope 配置模型
    loaders.py        # 画像与来源包加载
    normalizer.py     # 内容标准化
    event_dedup.py    # 跨语言事件去重
    analyzer.py       # AI 快速分析
    enricher.py       # AI 深度 enrichment
    evidence.py       # 证据策略
    selector.py       # 画像选择与排序
    run_store.py      # 阶段化运行存储
    scheduler.py      # 时间窗口与调度
    orchestrator.py   # 主控流程
    rendering.py      # Markdown/HTML 渲染
    delivery.py       # 分发管理
    sources/          # 来源适配器
    templates/        # 简报模板
  ...                 # Horizon 原始模块
data/
  foodscope/
    profiles/         # 内置画像
    source_packs/     # 内置来源包
docs/
  foodscope/          # FoodScope 文档
tests/
  foodscope/          # FoodScope 测试
```

## 14 天运营验收

发布到生产前，建议至少连续计划运行 14 天，覆盖五个画像、多个市场、来源故障、AI 无效返回和渠道故障。只有真实运行周期完成后，才能确认来源稳定性和成本边界。

周期结束后生成每源汇总：

```bash
uv run python scripts/foodscope_source_report.py \
  --runs data/runs \
  --output data/trials
```

## 许可证

FoodScope 保留上游 Horizon 的 MIT 许可证和版权声明。Horizon 相关代码版权归原作者所有；FoodScope 特有的画像、来源包、提示词、schema 和模板位于 `src/foodscope/` 和 `data/foodscope/` 下，同样遵循 MIT 许可证。

## 相关链接

- [Horizon 上游](https://github.com/Thysrael/Horizon)
- [FoodScope 配置指南](docs/foodscope/configuration.md)
- [FoodScope 来源包](docs/foodscope/source-packs.md)
- [FoodScope 画像](docs/foodscope/profiles.md)
- [FoodScope 运维](docs/foodscope/operations.md)

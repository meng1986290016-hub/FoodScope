# FoodScope 运行与运维

## 常用命令

```bash
# 手动运行，生成归档但不向外部分发
uv run python -m src.main --no-deliver

# 临时回看过去 12 小时
uv run python -m src.main --hours 12 --no-deliver

# 精确时间窗
uv run python -m src.main \
  --since 2026-07-23T00:00:00+08:00 \
  --until 2026-07-24T06:00:00+08:00 \
  --no-deliver

# 按配置持续调度
uv run python -m src.main --daemon

# 检查最近成功运行是否逾期
uv run python -m src.main --healthcheck
```

默认计划由 `schedule.timezone` 与 `schedule.cron` 决定，抓取范围由
`collection.lookback_hours` 决定。守护进程使用非阻塞文件锁；第二个实例会以
退出码 75 结束，避免重复运行。

如果 FoodScope 首轮候选数低于 `collection.adaptive_lookback_min_candidates`，
系统会在同一次 run 内按 `collection.adaptive_lookback_hours` 自动扩大回看窗口。
扩窗后的时间范围会写入 manifest；因此健康检查、恢复运行和最终简报都能看到
真实使用的抓取窗口。扩窗只解决低频断流，不会改变来源选择名册。

## 中断恢复和重新分发

每个阶段都原子落盘。恢复最近未完成运行：

```bash
uv run python -m src.main --resume latest
```

恢复指定运行：

```bash
uv run python -m src.main --resume RUN_ID
```

默认恢复不会再次对外分发。人工确认后需要重试分发时：

```bash
uv run python -m src.main --resume RUN_ID --redeliver
```

只有画像、schema 版本和已完成阶段连续性一致时才能恢复。已经成功发送且
事实哈希相同的渠道会标记为 `skipped`，防止重复发送。邮件按收件人、飞书按
卡片、通用 Webhook 按消息分别记录不可逆发送检查点；部分成功后重试只补发
失败部分，manifest 中只保存收件人散列，不保存邮箱地址。

## 运行目录

每次运行位于 `data/runs/<run_id>/`：

| 文件 | 含义 |
|---|---|
| `raw.json` | 原始候选 |
| `normalized.json` | 统一食品行业字段 |
| `scored.json` | AI 分类与评分 |
| `filtered.json` | 证据准入、去重和画像筛选；含可恢复的风险提醒标记 |
| `enriched.json` | “发生了什么”和原文明示关键事实；含隔离审计项 |
| `summary.json` | 简报元数据 |
| `facts.json` | 不可变事实快照 |
| `brief.md` / `brief.html` | 从同一事实快照渲染的成品 |
| `manifest.json` | 阶段、计数、隔离、来源指标、分发状态、耗时和哈希 |

`facts_sha256` 应在 Markdown、HTML、邮件、飞书、微信草稿和 MCP 读取结果中
一致。哈希不一致表示渠道不是从同一份事实生成，应停止分发并调查。

manifest 还固化 `source_selection`、`source_outcomes`、`token_usage`、
`eligible_sources`、`source_config_sha256`、`run_provenance` 和模型计价
快照。断点恢复会从这些字段还原来源指标，并把
本次新增 token 累加到原运行；不会因恢复而丢失或重复计算用量。模型单价未
配置时 `estimated_cost` 为 `null`，同时列出 `unpriced_models`。

`evidence_admission` 记录本次使用的 `loose`/`strict` 模式，以及权威来源、
多来源、单一来源、聚合回退和各类拒绝原因的数量。这些统计仅用于运行诊断
和审计，不作为简报正文标签展示。

最终简报按综合基础分分为“今日必读”（大于等于 6 分）和“今日新闻”
（小于 6 分）。每条只生成事件说明和原文明确支持的关键事实，并展示可点击
的原始来源名称及北京时间发布日期。

## 降级和故障隔离

- 单一来源失败：记录在抓取报告，其余来源继续；
- `core` 每次抓取，`extended` 默认两天轮换，`discovery` 默认三天轮换；
- 当日轮换结果不足配置目标数时，按稳定顺序补齐并记录实际来源集合；
- 首轮来源为空或失败时，最多再抓取 5 个确定性备用来源；
- 来源抓取默认最多 8 个全局并发、同域名 2 个并发；
- `core`、`extended`、`discovery` 分别最多尝试 3、2、1 次，并采用有界退避；
- 单条 AI 返回无效：重试后隔离该条，不中断整批；
- 单条深度分析失败：保留在审计快照，但不会进入 facts 或任何分发渠道；
- 单一分发渠道失败：记录失败，其余渠道继续；
- 官方证据缺失：法规/召回内容拒绝入选；
- 聚合原文解析失败：记录失败类型；宽松模式可按配置使用可归属媒体的聚合链接；
- 付费墙、登录、robots 或条款限制：不绕过，改用元数据或发现查询；
- 所有来源均失败或无成品：健康检查失败，运维人员应处理。

持久化或发送的错误只包含阶段和异常类型，不包含供应商原始文本。不要把
`.env`、Webhook URL、API token 或 SMTP 密码复制到 issue 和运行日志。

## 指标与 14 天验收

每日检查：

- 总候选、食品相关、入选、隔离数量；
- 各来源成功/空结果/失败状态；
- 日期解析率、独立事件数、重复率；
- 商业内容、赞助/新闻稿占比；
- AI token、估算成本和目标完成时长；
- 各渠道 `success`、`failure`、`disabled`、`skipped`。

发布前至少连续计划运行 14 天。验收应覆盖五个画像、多个市场、来源故障、AI 无效
返回和渠道故障。只有真实运行周期完成后，才能确认来源稳定性和成本边界；
离线 E2E 通过不能替代这项运营验收。

周期结束后生成每源汇总：

```bash
uv run python scripts/foodscope_source_report.py \
  --runs data/runs \
  --output data/trials
```

只有 `run_provenance="scheduled"` 的生产运行计入验收，并且必须形成连续
14 个业务日，同时每个来源至少要有 4 个实际抓取日；手工运行、历史回放、
零散日期和全是轮换跳过的记录不能拼成完整周期。未达到门槛时
报告状态为 `provisional`，来源层级和适配器建议显示为 `pending`。人工复核
`data/trials/source-trial-summary.md` 后，再把最终
`core`、`extended`、`discovery` 或 `disable` 结论写回静态来源包。
轮换日未选中的来源会记录为 `skipped_rotation`：它证明平台在该生产日正常
运行，但不计入该来源的抓取次数、成功率、候选量、token 或成本。

`--healthcheck` 同样只接受 `scheduled` 且已完成摘要的运行；刚完成的手工
回放不能掩盖计划任务已经逾期。

## 保留策略

守护进程在计划运行后执行保留策略：

- 原始到丰富阶段文件保留 30 天；
- 事实、简报、摘要和 manifest 保留 180 天；
- 遇到符号链接、未知文件或越界目录时跳过，不做递归删除。

若部署环境有额外审计要求，应在外部对象存储或备份系统中延长保留期。

## Docker Compose

```bash
cp data/config.foodscope.example.json data/config.json
cp .env.example .env
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

`data/` 作为持久卷挂载，`.env` 只读挂载。容器以非 root 用户运行，并用
`--healthcheck` 检查计划运行是否逾期。

## MCP 只读查看

FoodScope 提供配置校验、默认不分发的 pipeline 工具，以及有界只读资源：

- `foodscope://runs`
- `foodscope://runs/{run_id}/manifest`
- `foodscope://runs/{run_id}/stage/{stage}`
- `foodscope://runs/{run_id}/isolated`
- `foodscope://runs/{run_id}/brief/{format}`
- `foodscope://latest/brief/{format}`

生产环境应继续用文件系统权限限制 `data/`，MCP 资源不能替代操作系统访问控制。

## 恢复检查单

1. 运行 `--healthcheck` 并查看最近 manifest；
2. 确认失败来自来源、AI、模板还是渠道；
3. 校验配置与环境变量名，切勿打印实际密钥；
4. 使用 `--resume RUN_ID` 从最后完成阶段继续；
5. 先不分发验证成品和哈希；
6. 仅在人工确认后使用 `--redeliver`；
7. 将长期不稳定来源降级、改适配器或关闭。

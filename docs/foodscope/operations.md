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
事实哈希相同的渠道会标记为 `skipped`，防止重复发送。

## 运行目录

每次运行位于 `data/runs/<run_id>/`：

| 文件 | 含义 |
|---|---|
| `raw.json` | 原始候选 |
| `normalized.json` | 统一食品行业字段 |
| `scored.json` | AI 分类与评分 |
| `filtered.json` | 证据准入、去重和画像筛选 |
| `enriched.json` | 合规风险与商业机会补充 |
| `summary.json` | 简报元数据 |
| `facts.json` | 不可变事实快照 |
| `brief.md` / `brief.html` | 从同一事实快照渲染的成品 |
| `manifest.json` | 阶段、计数、隔离、来源指标、分发状态和哈希 |

`facts_sha256` 应在 Markdown、HTML、邮件、飞书、微信草稿和 MCP 读取结果中
一致。哈希不一致表示渠道不是从同一份事实生成，应停止分发并调查。

## 降级和故障隔离

- 单一来源失败：记录在抓取报告，其余来源继续；
- 单条 AI 返回无效：重试后隔离该条，不中断整批；
- 单一分发渠道失败：记录失败，其余渠道继续；
- 官方证据缺失：法规/召回内容拒绝入选；
- 付费墙、登录、robots 或条款限制：不绕过，改用元数据或发现查询；
- 所有来源均失败或无成品：健康检查失败，运维人员应处理。

错误详情会清理凭证和 URL 查询参数后再写入 manifest。不要把 `.env`、Webhook
URL、API token 或 SMTP 密码复制到 issue 和运行日志。

## 指标与 14 天验收

每日检查：

- 总候选、食品相关、入选、隔离数量；
- 各来源成功/空结果/失败状态；
- 日期解析率、独立事件数、重复率；
- 商业内容、赞助/新闻稿占比；
- AI token、估算成本和目标完成时长；
- 各渠道 `success`、`failure`、`disabled`、`skipped`。

发布前至少连续运行 14 天。验收应覆盖五个画像、多个市场、来源故障、AI 无效
返回和渠道故障。只有真实运行周期完成后，才能确认来源稳定性和成本边界；
离线 E2E 通过不能替代这项运营验收。

周期结束后生成每源汇总：

```bash
uv run python scripts/foodscope_source_report.py \
  --runs data/runs \
  --output data/trials
```

人工复核 `data/trials/source-trial-summary.md` 后，再把最终
`core`、`extended`、`discovery` 或 `disable` 结论写回静态来源包。

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

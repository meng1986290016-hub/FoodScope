# 参与 FoodScope 开发

FoodScope 采用“轻量 Horizon Fork + 食品行业扩展”结构。通用能力尽量留在
Horizon，食品领域模型、来源包、画像、证据规则和简报模板放在
`src/foodscope/` 与 `data/foodscope/`，以便后续同步上游。

## 本地验证

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests scripts
uv run mypy src
```

修改运行链路时还应验证：

```bash
uv run pytest tests/foodscope/test_e2e_foodscope.py -v
docker compose config --quiet
docker build -t foodscope:test .
docker run --rm foodscope:test uv run python -m src.main --help
git diff --check
```

离线 E2E 禁止访问公网，应使用 `httpx.MockTransport`、固定时间和受控 AI
响应，覆盖五个画像、四种语言、重复事件、来源失败、AI 失败及分发失败。

## 贡献来源或市场

来源包 PR 请包含：

- 稳定、唯一、可读的来源 ID；
- 官方首页和实际抓取入口；
- 适配器、证据等级、采集层级、市场、语言和主题；
- 网站访问边界：RSS/API/公开列表、robots、条款、登录和付费墙；
- 至少一个适配器或加载器测试；
- 最好附 14 天试运行指标，不得虚构生产验证结果。

优先使用官方 RSS/API。不要提交 Cookie、token、登录绕过、代理绕过或抓取受限
全文的实现。X 只接受官方 API，且新增观察项默认禁用。

## 贡献画像

画像应代表清晰用户角色，而不是只改几个数字。请说明：

- 目标用户和业务问题；
- 八类主题权重及其总和；
- 目标市场加权；
- 商业信息比例、探索位和单源上限；
- 风险提醒阈值；
- 与现有五个画像的实质差异。

新增画像必须通过配置测试，并在 E2E 中证明排序差异不会绕过证据准入。

## 贡献分类、提示词或模板

分类变更要同步更新领域模型、提示词、解析校验、画像、模板和文档。AI 输出必须
继续采用结构化模型校验；提示词中的判断不能替代确定性证据规则。

模板只能从 `BriefFacts` 渲染。不得让各渠道再次独立总结，因为这会造成邮件、
飞书、微信和归档事实不一致。新渠道必须：

- 使用相同 `facts_sha256`；
- 记录独立状态；
- 不因失败阻断其他渠道；
- 默认安全、显式启用；
- 对凭证和错误信息做脱敏。

## 版权、合规与证据

FoodScope 面向行业情报，不提供法律意见。贡献者应：

- 只保存必要元数据、短摘要和原文链接；
- 尊重版权、robots、站点条款和 API 许可；
- 明确标记赞助内容与新闻稿；
- 法规和食品安全结论引用官方证据；
- 把商业机会、风险识别表述为分析，不冒充事实或执法结论；
- 不在测试、fixtures、文档和提交历史中写入真实密钥或个人信息。

## 提交范围

尽量让每个提交保持单一目的。不要在食品扩展 PR 中顺手重构无关 Horizon
模块；若确需修改基座，请增加回归测试，证明关闭 FoodScope 后行为不变。

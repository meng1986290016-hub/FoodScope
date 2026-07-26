# FoodScope 可配置证据准入设计

**日期：** 2026-07-26  
**状态：** 已确认  
**范围：** FoodScope 发现资讯的证据准入、原始链接解析、配置与运行诊断

## 1. 背景

FoodScope 当前将 Google News、GDELT 等发现查询结果定义为三级证据。三级内容只有找到原始出处，或获得至少两个独立域名佐证，才允许进入简报。

2026-07-26 的真实运行抓取 55 条、规范化并分析 52 条，其中 38 条相关发现资讯因“缺少原始出处或两个独立域名”被拒绝，13 条因食品行业相关性不足被拒绝，1 条官方类别内容因缺少官方证据被拒绝，最终入选 0 条。Kimi 已成功完成内容分析，因此当前瓶颈位于证据准入层，而不是 AI 模型、评分或抓取总量。

一期产品需要在维持法规与食品安全可信度的前提下，增加新品、市场、原料技术、包装、零售餐饮和企业动态等商业资讯的可见度。FoodScope 仍是开源项目，使用者应能按自身风险偏好切换准入模式。

## 2. 目标

1. 默认采用宽松证据模式，使单一、可识别行业媒体报道的非官方类别内容可以进入正式简报。
2. 保留严格模式，供合规团队或高可信场景恢复现有三级证据要求。
3. 法规、标准、召回和食品安全内容始终要求官方证据，任何配置不得绕过。
4. 尽可能把 Google News 聚合链接解析为原媒体链接。
5. 链接解析失败不得阻断抓取、AI 分析或整次简报运行。
6. 保持现有最终简报模板不变。
7. 在运行清单和日志中记录准入模式、准入原因及汇总统计，便于诊断。

## 3. 非目标

- 本阶段不实现针对每条线索的自动二次搜索或跨来源补证据。
- 本阶段不建立媒体白名单、黑名单或完整媒体信誉评分系统。
- 本阶段不调整 AI 相关性提示词、重要性评分阈值或画像配额。
- 本阶段不新增“待验证线索”栏目。
- 本阶段不修改 Markdown、HTML、微信或飞书简报的现有展示结构。

## 4. 配置

FoodScope 顶层配置增加 `evidence`：

```json
{
  "evidence": {
    "mode": "loose",
    "resolve_original_urls": true,
    "allow_aggregator_fallback": true
  }
}
```

字段定义：

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `mode` | `"loose" \| "strict"` | `"loose"` | 非官方类别三级证据的准入模式 |
| `resolve_original_urls` | `bool` | `true` | 是否尝试把聚合链接解析为原媒体链接 |
| `allow_aggregator_fallback` | `bool` | `true` | 原文解析失败后，宽松模式是否允许使用可归属媒体的聚合链接 |

旧配置缺少 `evidence` 时自动采用以上默认值，不要求用户迁移配置。

## 5. 领域数据

发现来源在现有 `ContentItem.metadata` 和 `FoodIntelligence` 上记录以下数据：

| 字段 | 位置 | 含义 |
| --- | --- | --- |
| `resolved_original_url` | `metadata` | 成功解析出的原媒体 URL |
| `discovered_source_name` | `metadata` | Google News 或 GDELT 给出的发布媒体名称 |
| `publisher_domain` | `metadata` | 原媒体 URL 的可注册域名 |
| `original_url_resolution_status` | `metadata` | `resolved`、`fallback`、`failed` 或 `disabled` |
| `foodscope_admission_mode` | `metadata` | 本条内容实际使用的 `loose` 或 `strict` |
| `foodscope_admission_reason` | `metadata` | 确定性的准入或拒绝原因 |

`FoodIntelligence.original_source_url` 在解析成功时使用原媒体 URL。未解析成功时保持为空，聚合链接继续保存在 `ContentItem.url` 和 `FoodIntelligence.evidence_urls` 中。

这些字段用于策略判断、运行诊断和后续扩展，不改变当前简报模板。

## 6. 数据流

1. 发现适配器从 Google News 或 GDELT 获取候选。
2. 候选保留聚合 URL、媒体名称、查询和 provider 元数据。
3. 当 `resolve_original_urls=true` 时，原始链接解析器尝试取得最终媒体 URL。
4. 解析器把结果与状态写入候选元数据；失败只记录状态，不抛出导致批次失败的异常。
5. 规范化阶段把已解析 URL 写入 `FoodIntelligence.original_source_url`。
6. AI 分析继续完成食品行业相关性、分类、重要性和其他结构化字段。
7. `EvidencePolicy` 根据内容类别、配置模式、媒体归属和证据 URL 作出准入决定。
8. 选择、画像平衡、深度分析、摘要和分发继续沿用现有流程。
9. Run manifest 汇总每种准入和拒绝原因的数量。

## 7. 准入规则

### 7.1 永久严格的官方类别

以下类别不受 `evidence.mode` 影响：

- `regulations_standards`
- `food_safety_recalls`

这两类内容必须存在 `official_evidence_urls`。缺少官方证据时固定拒绝，原因记为 `official evidence required`。

### 7.2 一级和二级证据

一级与二级证据继续按照现有权威证据规则准入。赞助内容和新闻稿继续执行现有证据质量扣分，不因宽松模式免除。

### 7.3 三级证据：宽松模式

非官方类别的三级内容满足以下全部条件时可以准入：

1. AI 判断 `foodscope_relevant=true`。
2. 至少存在一个有效的 HTTP/HTTPS 证据链接。
3. 满足以下媒体归属条件之一：
   - 成功解析出非聚合站点的原媒体 URL 和域名；
   - 解析失败，但 `allow_aggregator_fallback=true`，且聚合结果包含非空的 `discovered_source_name`。

成功解析原媒体 URL 时，准入原因记为 `accepted single attributable source`。使用聚合链接回退时，准入原因记为 `accepted attributable aggregator fallback`。

以下内容仍拒绝：

- 媒体名称为空且无法解析原媒体域名；
- 没有有效 HTTP/HTTPS 证据链接；
- 已被标记为隔离；
- AI 判断与食品行业不相关；
- 属于官方类别但缺少官方证据。

### 7.4 三级证据：严格模式

严格模式维持现有规则：必须存在 `original_source_url`，或 `evidence_urls` 覆盖至少两个独立可注册域名。拒绝原因保持 `discovery requires original source or two domains`。

### 7.5 四级证据

四级弱信号保持现有规则：必须回链到原始出处，并关联一级、二级或三级证据后才可能准入。宽松模式不直接放行四级内容。

## 8. 原始链接解析

解析器是独立、可测试的组件，不把网络解析逻辑放入 `EvidencePolicy`。

解析要求：

- 仅处理 `http` 和 `https` URL。
- 禁止访问回环、链路本地、私有地址和其他非公网目标。
- 限制重定向次数、请求超时、响应体大小和并发数。
- 不发送凭证、Cookie 或用户私有 Header。
- 优先使用重定向结果；只有 Google News 需要时才解析有上限的 HTML 元数据。
- 最终 URL 仍指向聚合域名时，不视为成功解析。
- 单条解析失败返回结构化状态，不抛出中断整个来源或运行的异常。
- 同一聚合 URL 在单次运行内只解析一次。

第一期只实现当前发现源所需的解析策略，不构建通用网页爬虫。

## 9. 失败与降级

- `resolve_original_urls=false` 时直接记录 `disabled`。
- 解析超时、无有效跳转、无效 URL 或目标被安全策略拒绝时记录 `failed`。
- 宽松模式且允许聚合回退、媒体名称可识别时记录 `fallback` 并继续准入。
- 严格模式下解析失败仍执行现有双域名规则。
- 单条失败不得改变同批其他候选的处理结果。
- GDELT 或 Google News provider 失败继续沿用现有 provider 隔离和批次容错。
- Manifest 不记录异常堆栈、凭证或响应正文，只保存有限的状态和安全错误分类。

## 10. 运行诊断

Run manifest 增加证据准入汇总，至少包含：

```json
{
  "evidence_admission": {
    "mode": "loose",
    "accepted_authoritative": 0,
    "accepted_corroborated": 0,
    "accepted_single_source": 0,
    "accepted_aggregator_fallback": 0,
    "rejected_not_relevant": 0,
    "rejected_official_evidence_required": 0,
    "rejected_unknown_publisher": 0,
    "rejected_strict_evidence": 0
  }
}
```

计数由确定性的策略结果生成。运行日志使用相同原因分类，避免 manifest 与控制台统计口径不一致。

最终简报继续使用现有模板，不显示新增的证据状态、准入模式或诊断标签。

## 11. 组件边界

- 配置模型：定义并校验 `EvidenceConfig`，向现有 FoodScope 配置提供默认值。
- 原始链接解析器：输入聚合 URL，输出解析 URL、发布域名、状态和安全错误分类。
- 发现适配器：调用解析器并把结果附加到候选元数据。
- 规范化器：把 `resolved_original_url` 映射到 `FoodIntelligence.original_source_url`。
- `EvidencePolicy`：只消费结构化字段和配置，不执行网络请求。
- Orchestrator/RunStore：汇总并持久化准入结果，不重新实现策略判断。
- 简报渲染器：保持不变。

## 12. 测试

必须覆盖：

1. 旧配置缺少 `evidence` 时默认得到宽松模式和两个启用的布尔开关。
2. 配置拒绝未知 `mode`。
3. 宽松模式接受单一、可识别媒体的非官方三级内容。
4. 严格模式拒绝同一内容。
5. 宽松和严格模式都拒绝缺少官方 URL 的法规、标准、召回及食品安全内容。
6. 无媒体名称且无法解析原媒体的聚合结果被拒绝。
7. 原始链接解析成功后写入原媒体 URL 和发布域名。
8. 解析失败时，根据 `allow_aggregator_fallback` 决定宽松模式是否准入。
9. 私有网络、回环地址、非 HTTP/HTTPS URL 和超限重定向被安全拒绝。
10. 同一 URL 在单次运行内不重复解析。
11. 单条解析失败不会导致同批候选失败。
12. 新闻稿和赞助内容继续扣减证据质量分。
13. 四级弱信号不会被宽松模式直接放行。
14. Manifest 能按统一原因统计准入与拒绝数量。
15. 现有简报模板渲染快照或断言保持不变。
16. `strict` 模式通过现有证据策略回归测试。

实现采用测试驱动方式：每一项行为先添加失败测试，再做最小实现。

## 13. 验收

代码验收：

- FoodScope 全量测试通过。
- 项目全量测试通过。
- Ruff、Mypy 和 `git diff --check` 通过。
- 现有简报模板无差异。

真实运行验收：

- 使用默认宽松模式执行一次 `python -m src.main --no-deliver`。
- 不再因为“所有三级发现资讯只有单一来源”而系统性产生 0 条入选。
- 相关性不足、来源不可归属和缺少必要证据的内容仍被拒绝。
- 官方类别中缺少官方证据的入选数为 0。
- Manifest 中的证据准入计数与逐条原因一致。
- 再使用严格模式执行受控测试，确认现有严格行为保持不变。

## 14. 后续扩展

自动搜索企业公告、寻找第二独立来源、媒体信誉分和待验证线索栏目留到后续阶段。当前字段和组件边界应允许后续补证据模块在准入策略之前运行，但本阶段不实现这些能力。

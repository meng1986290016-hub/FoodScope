# FoodScope 来源包

来源包解决“系统默认值”和“用户偏好”之间的冲突：仓库提供经过筛选的起点，
使用者可以自由组合、关闭、覆盖或新增来源，不会被固定在食品安全或市场资讯
的单一偏向中。

## 内置来源包

| ID | 侧重点 |
|---|---|
| `official_evidence` | 法规、标准、食品安全与召回的一手证据 |
| `global_industry` | 全球食品行业媒体和企业动态 |
| `product_launches` | 新品、配方、品牌与上市信息 |
| `ingredients_rd` | 原料、科研与食品技术 |
| `packaging_processing` | 包装、标签、加工和制造 |
| `retail_foodservice` | 零售、餐饮和渠道 |
| `research_data` | 研究机构、市场与消费数据 |
| `japan` | 日本市场 |
| `korea` | 韩国市场 |
| `southeast_asia` | 东南亚市场 |
| `discovery_queries` | 多语言发现查询，用于补足未知来源 |
| `x_watch` | 经筛选的 X 观察名单；默认全部关闭 |

示例配置默认兼顾官方证据、商业媒体、新品和多语言发现查询，不含 Reddit。来源文件位于
`data/foodscope/source_packs/`，每条记录都有稳定 `id`、入口 URL、适配器、
证据等级、采集层级、市场、语言和主题提示。

## 组合来源包

想看更多市场行情，可把市场、零售和新品包放进配置：

```json
{
  "foodscope": {
    "source_packs": [
      "global_industry",
      "product_launches",
      "retail_foodservice",
      "research_data",
      "official_evidence"
    ]
  }
}
```

同一来源若出现在多个包中，会按来源 ID 合并，并保留所有所属包；不会重复抓取。

`collection_tier` 同时决定抓取频率、优先级和失败重试预算：`core` 每次运行
且最多尝试 3 次，`extended` 默认两天轮换且最多 2 次，`discovery` 默认三天
轮换且只尝试 1 次。首轮空/失败会触发有上限的备用来源波次。所有层级仍受
全局和单域名并发限制，避免一个站点拖垮整次简报。

`discovery_queries` 是第一期的稳定兜底层：当直连行业媒体或官方源低频断流时，
Google News / GDELT 查询可补足新品、市场和企业动态。GDELT 在生产中会按
provider 级别限并发，避免多语言查询同时触发 429。

## 关闭或覆盖单个来源

不必复制整个内置包。使用 `source_overrides` 按 ID 修改：

```json
{
  "foodscope": {
    "source_overrides": {
      "example-source-id": {
        "enabled": false
      },
      "another-source-id": {
        "collection_tier": "core",
        "markets": ["US", "EU"]
      }
    }
  }
}
```

覆盖后仍会重新经过完整的 `FoodSourceSpec` 校验。建议只覆盖确实需要变化的
字段，方便后续同步上游来源包更新。

## 新增自己的来源包

在来源目录新建 `my_market.json`：

```json
{
  "id": "my_market",
  "name": "我的市场来源",
  "sources": [
    {
      "id": "my-food-media",
      "name": "My Food Media",
      "url": "https://example.com/feed.xml",
      "adapter": "rss",
      "enabled": true,
      "evidence_tier": 2,
      "collection_tier": "extended",
      "packs": [],
      "markets": ["US"],
      "languages": ["en"],
      "categories": ["consumer_trends"],
      "options": {}
    }
  ]
}
```

然后把 `my_market` 加入 `foodscope.source_packs`。可用的适配器包括：

- `rss`：优先选择，读取标题、链接、日期和有限正文；
- `json_api`：公开 JSON API；
- `html_list`：稳定、允许访问的公开列表页；
- `document_index`：法规、公告或文件索引；
- `discovery_query`：多语言发现查询；
- `x_official_api`：X 官方 API，默认禁用。

适配器只保留有界元数据和必要摘要，不绕过登录、付费墙、robots 或网站条款。
遇到受限页面时，应改用公开 RSS、官方 API、原始公告链接或仅元数据模式。

## X 的合规边界

`x_watch` 中的观察账号默认全部 `enabled=false`。启用前必须同时设置：

```json
{
  "foodscope": {
    "x_access_mode": "official_api",
    "x_bearer_token_env": "X_BEARER_TOKEN",
    "source_overrides": {
      "目标来源ID": {"enabled": true}
    }
  }
}
```

FoodScope 不使用浏览器 Cookie、页面抓取或非官方绕过方式访问 X。API 额度、
许可、内容保留和再分发责任由部署者依据当时的 X 开发者条款确认。

## 证据与来源层级

- `evidence_tier=1`：政府、监管、标准或原始企业公告；
- `evidence_tier=2`：专业行业媒体；
- `evidence_tier=3`：发现来源，需要原始链接或跨域佐证；
- `evidence_tier=4`：弱信号，只有链接到更强证据时才可能入选。

法规与食品安全内容必须带官方证据链接。赞助内容和新闻稿会明确标记，并降低
证据质量分，不会因为商业信息丰富而冒充独立报道。

## 来源试运行与筛选

正式设为核心来源前，建议运行 14 天并查看每源的：

- 抓取成功率、发布日期解析率；
- 食品行业相关率和最终入选量；
- 独立有效事件数、重复率；
- 商业信息占比、赞助内容占比；
- AI token 和估算成本；
- robots、登录、付费墙或条款限制。

代码只有在连续完成 14 个计划生产日、且该来源在窗口内至少实际抓取 4 天后，
才给出 `core`、`extended`、`discovery`、`disable` 和适配器模式建议；此前
统一显示 `provisional/pending`。最终取舍仍由维护者审核，离线测试不能把
来源包标记为“生产验证完成”。

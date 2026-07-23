# FoodScope 一期来源与发现查询目录

## 1. 使用方式

本目录是 FoodScope Horizon 食品行业版的首批采集配置基线，核验日期为 2026-07-23。40 个直连来源是 40 个独立配置入口，不等于 40 套采集代码；RSS、JSON API、HTML 列表和 PDF/HWPX 等同类入口复用通用适配器。

- P0：首个可运行版本必须启用并通过契约测试。
- P1：在 14 天试运行期内启用并通过契约测试。
- 一级：监管机构、标准组织和政府数据。
- 二级：行业媒体，只采集标题、日期、链接和允许使用的短摘要，不绕过登录或付费墙。
- 所有页面都保留原始链接；法规、标准、召回和安全事件只能把官方入口作为主证据。
- 若来源的使用条款、robots 或访问限制不允许自动抓取，则禁用正文提取，仅保留链接元数据或改用该域名的发现查询。

## 2. 40 个直连来源

### 2.1 全球组织

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 1 | `global_codex_news` | P0/一级 | [Codex News and Events](https://www.fao.org/fao-who-codexalimentarius/news-and-events/en/) | HTML 列表＋正文 | 英语 | 法规与标准、食品安全 |
| 2 | `global_fao_food_safety` | P1/一级 | [FAO Newsroom](https://www.fao.org/newsroom/en/) | HTML 列表，关键词过滤 `food safety`、`food standards`、`food technology` | 英语 | 食品安全、原料与技术 |
| 3 | `global_who_news` | P1/一级 | [WHO Newsroom](https://www.who.int/news-room) | HTML 列表，关键词过滤 `food safety`、`foodborne`、`nutrition labelling` | 英语 | 食品安全、法规与标准 |
| 4 | `global_wto_sps` | P0/一级 | [WTO ePing SPS/TBT](https://epingalert.org/en) | 公开检索页；食品、饮料、添加剂、包装接触材料关键词 | 多语言 | 法规与标准、包装与标签 |

### 2.2 美国

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 5 | `us_fda_food_recalls` | P0/一级 | [FDA Food Safety Recalls RSS](https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/food-safety-recalls/rss.xml) | RSS＋正文 | 英语 | 食品安全与召回 |
| 6 | `us_fda_outbreaks` | P0/一级 | [FDA Outbreaks RSS](https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/fda-outbreaks/rss.xml) | RSS＋正文 | 英语 | 食品安全与召回 |
| 7 | `us_openfda_enforcement` | P0/一级 | [openFDA Food Enforcement API](https://api.fda.gov/food/enforcement.json) | JSON API，按 `report_date` 增量抓取 | 英语 | 食品安全与召回、包装与标签 |
| 8 | `us_fda_hfp_news` | P0/一级 | [FDA Human Foods Program News](https://www.fda.gov/food/news-events-human-foods-program) | HTML 列表＋正文 | 英语 | 法规与标准、原料与技术 |
| 9 | `us_fda_food_guidance` | P0/一级 | [FDA Food Guidance and Regulation](https://www.fda.gov/guidance-regulation-0) | HTML 列表＋PDF | 英语 | 法规与标准、包装与标签 |
| 10 | `us_fsis_recalls` | P0/一级 | [USDA FSIS Recall API](https://www.fsis.usda.gov/fsis/api/recall/v/1) | JSON API | 英语 | 食品安全与召回 |
| 11 | `us_fsis_news` | P1/一级 | [USDA FSIS News and Press Releases](https://www.fsis.usda.gov/news-events/news-press-releases) | HTML 列表＋正文 | 英语 | 食品安全、法规与标准 |

### 2.3 欧盟与英国

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 12 | `eu_ec_food_safety_news` | P0/一级 | [European Commission Food Safety](https://food.ec.europa.eu/food-safety_en) | HTML 新闻列表＋正文 | 英语 | 法规与标准、食品安全 |
| 13 | `eu_rasff` | P0/一级 | [RASFF Window](https://webgate.ec.europa.eu/rasff-window/screen/search) | 公开查询结果；若结构变化则降级为消费者门户列表 | 英语 | 食品安全与召回 |
| 14 | `eu_food_fraud_reports` | P1/一级 | [EU Agri-Food Fraud Monthly Reports](https://food.ec.europa.eu/food-safety/acn/ffn-monthly_en) | HTML 列表＋PDF | 英语 | 食品安全与召回、企业动态 |
| 15 | `eu_efsa_news` | P0/一级 | [EFSA News RSS](https://www.efsa.europa.eu/en/press/rss) | RSS＋正文 | 英语 | 食品安全、原料与技术 |
| 16 | `eu_efsa_publications` | P0/一级 | [EFSA Publications RSS](https://www.efsa.europa.eu/en/publications/rss) | RSS，按食品配料、包装、营养、污染物等主题过滤 | 英语 | 原料与技术、法规与标准 |
| 17 | `eu_eurlex_food_law` | P0/一级 | [EUR-Lex Predefined RSS Alerts](https://eur-lex.europa.eu/content/help/search/predefined-rss.html?locale=en) | RSS；监测 OJ L 与委员会提案，再按食品词表过滤 | 多语言 | 法规与标准、包装与标签 |
| 18 | `uk_fsa_food_alerts` | P0/一级 | [UK FSA Food Alerts API](https://data.food.gov.uk/food-alerts/id.json) | JSON API，按发布日期增量抓取 | 英语 | 食品安全与召回 |
| 19 | `uk_fsa_news` | P0/一级 | [UK FSA News and Alerts](https://www.food.gov.uk/news-alerts) | HTML 列表＋正文 | 英语 | 法规与标准、消费趋势 |

### 2.4 日本

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 20 | `jp_caa_food_labeling` | P0/一级 | [消费者厅食品表示](https://www.caa.go.jp/policies/policy/food_labeling/information) | HTML 列表＋PDF | 日语 | 包装与标签、法规与标准 |
| 21 | `jp_caa_food_recalls` | P0/一级 | [消费者厅食品表示召回](https://www.caa.go.jp/policies/policy/food_labeling/food_labeling_recall) | HTML 列表＋详情 | 日语 | 食品安全与召回、包装与标签 |
| 22 | `jp_caa_food_standards` | P0/一级 | [消费者厅食品卫生基准新着](https://www.caa.go.jp/policies/policy/standards_evaluation/appliance/archive/) | HTML 列表＋PDF | 日语 | 法规与标准、包装与标签 |
| 23 | `jp_mhlw_food_safety` | P1/一级 | [厚生劳动省食品](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/shokuhin/) | HTML 列表＋PDF | 日语 | 食品安全、法规与标准 |
| 24 | `jp_mhlw_recall_system` | P1/一级 | [食品卫生申请等系统](https://i2fas.mhlw.go.jp/about.htm) | 公开召回列表；以管理编号和发布日期增量抓取 | 日语 | 食品安全与召回 |
| 25 | `jp_maff_press` | P0/一级 | [农林水产省报道发布](https://www.maff.go.jp/j/press/) | HTML 列表，按食品产业、技术、标准和出口过滤 | 日语 | 原料与技术、企业动态 |

### 2.5 韩国

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 26 | `kr_mfds_press` | P0/一级 | [MFDS 보도자료](https://www.mfds.go.kr/brd/m_99/list.do) | HTML 列表＋PDF/HWPX；按食品部门和关键词过滤 | 韩语 | 法规与标准、食品安全 |
| 27 | `kr_mfds_standards` | P0/一级 | [MFDS 고시전문](https://www.mfds.go.kr/brd/m_211/list.do) | HTML 列表＋PDF/HWPX | 韩语 | 法规与标准、包装与标签 |
| 28 | `kr_imported_food_news` | P1/一级 | [进口食品信息마루](https://impfood.mfds.go.kr/CFBBB02F01) | HTML 列表＋PDF/HWPX | 韩语 | 食品安全与召回、法规与标准 |

### 2.6 东南亚

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 29 | `sg_sfa_food_alerts` | P0/一级 | [SFA Food Alerts RSS](https://www.sfa.gov.sg/rss/annual-listing-food-alerts) | RSS＋正文 | 英语 | 食品安全与召回 |
| 30 | `sg_sfa_newsroom` | P0/一级 | [SFA Newsroom RSS](https://www.sfa.gov.sg/rss/newsroom) | RSS＋正文 | 英语 | 法规与标准、原料与技术 |
| 31 | `my_moh_food_safety` | P1/一级 | [Malaysia MOH Food Safety and Quality Programme](https://www.moh.gov.my/en/corporate-info/division-information/food-safety-and-quality-programme) | HTML 页面变更监测＋站内官方链接 | 英语/马来语 | 法规与标准、食品安全 |
| 32 | `th_fda_food_news` | P1/一级 | [Thai FDA News](https://www.fda.moph.go.th/news/) | HTML 列表，食品分类过滤 | 泰语 | 法规与标准、食品安全 |
| 33 | `vn_vfa_news` | P1/一级 | [Vietnam Food Administration](https://vfa.gov.vn/) | HTML 列表＋正文/PDF | 越南语 | 法规与标准、食品安全 |

### 2.7 行业媒体

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 34 | `media_foodnavigator` | P0/二级 | [FoodNavigator](https://www.foodnavigator.com/) | HTML 列表；只取公开元数据和短摘要 | 英语 | 产品创新、原料与技术、消费趋势 |
| 35 | `media_beveragedaily` | P0/二级 | [BeverageDaily](https://www.beveragedaily.com/) | HTML 列表；只取公开元数据和短摘要 | 英语 | 产品创新、消费趋势 |
| 36 | `media_foodbusinessnews` | P0/二级 | [Food Business News RSS](https://www.foodbusinessnews.net/rss) | RSS | 英语 | 产品创新、企业动态、零售餐饮 |
| 37 | `media_ift_foodtechnology` | P0/二级 | [IFT Food Technology](https://www.ift.org/foodtechnology/) | HTML 列表；只取公开元数据和短摘要 | 英语 | 原料与技术、产品创新 |
| 38 | `media_packagingeurope` | P0/二级 | [Packaging Europe](https://packagingeurope.com/) | HTML 列表；只取公开元数据和短摘要 | 英语 | 包装与标签 |
| 39 | `media_foodbev` | P0/二级 | [FoodBev Media](https://www.foodbev.com/blog) | HTML 列表；只取公开元数据和短摘要 | 英语 | 产品创新、企业动态、消费趋势 |
| 40 | `media_foodsafetymagazine` | P1/二级 | [Food Safety Magazine News](https://www.food-safety.com/topics/296-news) | RSS 优先，HTML 列表降级 | 英语 | 食品安全、原料与技术 |

## 3. 20 组多语言发现查询

### 3.1 查询配置字段

每组查询包含以下字段：

```json
{
  "id": "en_product_launch",
  "enabled": true,
  "providers": ["google_news", "gdelt"],
  "query": "(food OR beverage) (\"new product\" OR launch OR innovation)",
  "languages": ["en"],
  "markets": ["US", "EU", "GB", "GLOBAL"],
  "category_hint": "product_innovation",
  "max_candidates_per_provider": 20,
  "max_candidates_after_dedup": 12,
  "source_tier": 3
}
```

Google News 和 GDELT 均执行英语及东南亚英语查询；日语和韩语默认只执行 Google News。时间窗由全局 `collection.lookback_hours` 控制，不把相对日期硬编码进查询式。

### 3.2 查询清单

| # | Query ID | 市场/语言 | 默认查询式 | 分类提示 |
|---|---|---|---|---|
| 1 | `en_product_launch` | 全球/英语 | `(food OR beverage) ("new product" OR launch OR innovation)` | 产品创新 |
| 2 | `en_ingredient_innovation` | 全球/英语 | `("food ingredient" OR "novel ingredient") (launch OR innovation OR technology)` | 原料与技术 |
| 3 | `en_fermentation` | 全球/英语 | `("precision fermentation" OR "biomass fermentation" OR "food fermentation")` | 原料与技术 |
| 4 | `en_alternative_protein` | 全球/英语 | `("alternative protein" OR "plant-based" OR "cultivated meat") (launch OR approval OR scale)` | 原料与技术 |
| 5 | `en_functional_food` | 全球/英语 | `("functional food" OR nutraceutical OR probiotic OR prebiotic) (ingredient OR product)` | 产品创新 |
| 6 | `en_reformulation` | 全球/英语 | `("sugar reduction" OR "sodium reduction" OR "clean label") food` | 原料与技术 |
| 7 | `en_food_packaging` | 全球/英语 | `("food packaging" OR "beverage packaging") (recyclable OR active OR smart OR innovation)` | 包装与标签 |
| 8 | `en_processing_technology` | 全球/英语 | `("food processing technology" OR "non-thermal processing" OR "food manufacturing technology")` | 原料与技术 |
| 9 | `en_consumer_trends` | 全球/英语 | `("food consumer trend" OR "beverage trend") (survey OR report OR market)` | 消费趋势 |
| 10 | `en_retail_foodservice` | 全球/英语 | `(retail OR restaurant OR foodservice) ("new product" OR menu OR concept) food` | 零售餐饮 |
| 11 | `en_food_regulation` | 全球/英语 | `("food labelling" OR "food labeling" OR "food additive" OR "novel food") (regulation OR guidance OR approval)` | 法规与标准 |
| 12 | `en_food_safety` | 全球/英语 | `("food recall" OR "undeclared allergen" OR contamination OR "food fraud")` | 食品安全与召回 |
| 13 | `en_company_moves` | 全球/英语 | `("food company" OR "beverage company") (acquisition OR investment OR partnership OR "new facility")` | 企业动态 |
| 14 | `ja_product_launch` | 日本/日语 | `食品 新商品 OR 飲料 新商品 OR 食品 開発` | 产品创新 |
| 15 | `ja_ingredient_technology` | 日本/日语 | `食品 原料 技術 OR 発酵 技術 OR 代替たんぱく` | 原料与技术 |
| 16 | `ja_regulation_recall` | 日本/日语 | `食品表示 改正 OR 食品添加物 規格 OR 食品 回収 OR アレルギー 表示漏れ` | 法规与标准、食品安全 |
| 17 | `ko_product_launch` | 韩国/韩语 | `식품 신제품 OR 음료 신제품 OR 제품 개발` | 产品创新 |
| 18 | `ko_ingredient_technology` | 韩国/韩语 | `식품 원료 기술 OR 발효 기술 OR 대체 단백질` | 原料与技术 |
| 19 | `ko_regulation_recall` | 韩国/韩语 | `식품 표시 기준 개정 OR 식품 첨가물 OR 식품 회수` | 法规与标准、食品安全 |
| 20 | `en_southeast_asia` | 东南亚/英语 | `("Singapore" OR Malaysia OR Thailand OR Vietnam OR ASEAN) ("food innovation" OR "food labelling" OR "food recall" OR "novel food")` | 多分类 |

### 3.3 全局过滤与准入

- 默认排除：食谱、家庭烹饪、餐厅点评、个人减肥建议、药品、化妆品、宠物食品，以及与食品加工无关的纯农业资讯。
- `animal feed` 仅在饲料安全、食品链风险或法规标准语境下保留。
- 同一查询每个 provider 最多取 20 条；查询内去重后最多保留 12 条，全部查询合并后再执行全局去重。
- 已列入 40 个直连来源的域名命中发现查询时，与直连记录合并，不重复计入候选。
- 未知域名一律标记为三级。无发布日期、无法回链原文、只有聚合页或疑似软文的结果直接隔离。
- 法规、标准、召回和安全查询必须找到官方原始出处；其他查询必须找到原始企业公告或至少两个独立可信来源，才能进入 AI 深度分析。

## 4. 来源健康与降级规则

- RSS/API：响应 Schema、日期字段和唯一标识写入契约 fixture；连续三次失败后暂停该来源，并在运行报告中列出。
- HTML：使用语义选择器和结构断言，不依赖完整 CSS 层级；页面结构变化时保存脱敏失败样本。
- PDF：优先文本层提取，无文本层时才启用 OCR；HWPX 通过 ZIP/XML 解析，HWP 二进制附件只使用同页 PDF 版本。
- JavaScript 页面：先寻找公开 API 或服务端 HTML；只有条款允许且没有稳定入口时才启用 Playwright。
- 降级顺序：结构化 API → RSS/Atom → HTML 列表 → 同域名 Google News 查询。降级结果仍保留原始来源等级，但在运行元数据中记录采集方式。
- P0 来源任何一个失败不会阻塞简报；P0 连续三次失败会令整次运行标记为 `degraded`，但其他来源和渠道继续执行。

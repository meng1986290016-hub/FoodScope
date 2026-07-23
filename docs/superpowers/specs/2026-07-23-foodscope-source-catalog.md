# FoodScope 一期来源与发现查询目录

## 1. 使用方式

本目录是 FoodScope Horizon 食品行业版的首批采集配置基线，核验日期为 2026-07-23。首批 40 个直连来源按 `20 个官方入口 + 20 个行业媒体` 配置，在维持法规、安全底线覆盖的同时，提高新品、技术、市场和企业动态的供给。官方入口是一期基线；20 个行业媒体是待产品负责人逐个筛选和试跑验证的首轮暂定组合，候选范围见[《行业媒体与商业信号源候选池》](2026-07-23-foodscope-industry-media-longlist.md)。40 个来源是 40 个独立配置入口，不等于 40 套采集代码；RSS、JSON API、HTML 列表和 PDF/HWPX 等同类入口复用通用适配器。

- P0：首个可运行版本必须启用并通过契约测试。
- P1：在 14 天试运行期内启用并通过契约测试。
- 一级：监管机构、标准组织和政府数据，共 20 个；聚焦高风险、高时效的法规、召回和安全证据。
- 二级：行业媒体，共 20 个；聚焦新品、原料技术、包装、消费、零售餐饮、投融资和企业动作，只采集标题、日期、链接和允许使用的短摘要，不绕过登录或付费墙。
- 所有页面都保留原始链接；法规、标准、召回和安全事件只能把官方入口作为主证据。
- 付费合作、赞助内容、供应商观点和新闻稿必须显式标记，证据权重低于独立编辑报道，不能单独支撑法规风险、市场规模或技术效果结论。
- 若来源的使用条款、robots 或访问限制不允许自动抓取，则禁用正文提取，仅保留链接元数据或改用该域名的发现查询。

## 2. 40 个直连来源

### 2.1 官方入口（20 个）

#### 全球组织

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 1 | `global_codex_news` | P0/一级 | [Codex News and Events](https://www.fao.org/fao-who-codexalimentarius/news-and-events/en/) | HTML 列表＋正文 | 英语 | 法规与标准、食品安全 |
| 2 | `global_wto_sps` | P0/一级 | [WTO ePing SPS/TBT](https://epingalert.org/en) | 公开检索页；食品、饮料、添加剂、包装接触材料关键词 | 多语言 | 法规与标准、包装与标签 |

#### 美国

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 3 | `us_fda_food_recalls` | P0/一级 | [FDA Food Safety Recalls RSS](https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/food-safety-recalls/rss.xml) | RSS＋正文 | 英语 | 食品安全与召回 |
| 4 | `us_fda_outbreaks` | P0/一级 | [FDA Outbreaks RSS](https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/fda-outbreaks/rss.xml) | RSS＋正文 | 英语 | 食品安全与召回 |
| 5 | `us_openfda_enforcement` | P0/一级 | [openFDA Food Enforcement API](https://api.fda.gov/food/enforcement.json) | JSON API，按 `report_date` 增量抓取 | 英语 | 食品安全与召回、包装与标签 |
| 6 | `us_fda_food_guidance` | P0/一级 | [FDA Food Guidance and Regulation](https://www.fda.gov/guidance-regulation-0) | HTML 列表＋PDF | 英语 | 法规与标准、包装与标签 |
| 7 | `us_fsis_recalls` | P0/一级 | [USDA FSIS Recall API](https://www.fsis.usda.gov/fsis/api/recall/v/1) | JSON API | 英语 | 食品安全与召回 |

#### 欧盟与英国

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 8 | `eu_ec_food_safety_news` | P0/一级 | [European Commission Food Safety](https://food.ec.europa.eu/food-safety_en) | HTML 新闻列表＋正文 | 英语 | 法规与标准、食品安全 |
| 9 | `eu_rasff` | P0/一级 | [RASFF Window](https://webgate.ec.europa.eu/rasff-window/screen/search) | 公开查询结果；若结构变化则降级为消费者门户列表 | 英语 | 食品安全与召回 |
| 10 | `eu_efsa_news` | P0/一级 | [EFSA News RSS](https://www.efsa.europa.eu/en/press/rss) | RSS＋正文 | 英语 | 食品安全、原料与技术 |
| 11 | `eu_eurlex_food_law` | P0/一级 | [EUR-Lex Predefined RSS Alerts](https://eur-lex.europa.eu/content/help/search/predefined-rss.html?locale=en) | RSS；监测 OJ L 与委员会提案，再按食品词表过滤 | 多语言 | 法规与标准、包装与标签 |
| 12 | `uk_fsa_food_alerts` | P0/一级 | [UK FSA Food Alerts API](https://data.food.gov.uk/food-alerts/id.json) | JSON API，按发布日期增量抓取 | 英语 | 食品安全与召回 |

#### 日本

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 13 | `jp_caa_food_labeling` | P0/一级 | [消费者厅食品表示](https://www.caa.go.jp/policies/policy/food_labeling/information) | HTML 列表＋PDF | 日语 | 包装与标签、法规与标准 |
| 14 | `jp_caa_food_recalls` | P0/一级 | [消费者厅食品表示召回](https://www.caa.go.jp/policies/policy/food_labeling/food_labeling_recall) | HTML 列表＋详情 | 日语 | 食品安全与召回、包装与标签 |
| 15 | `jp_caa_food_standards` | P0/一级 | [消费者厅食品卫生基准新着](https://www.caa.go.jp/policies/policy/standards_evaluation/appliance/archive/) | HTML 列表＋PDF | 日语 | 法规与标准、包装与标签 |

#### 韩国

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 16 | `kr_mfds_press` | P0/一级 | [MFDS 보도자료](https://www.mfds.go.kr/brd/m_99/list.do) | HTML 列表＋PDF/HWPX；按食品部门和关键词过滤 | 韩语 | 法规与标准、食品安全 |
| 17 | `kr_mfds_standards` | P0/一级 | [MFDS 고시전문](https://www.mfds.go.kr/brd/m_211/list.do) | HTML 列表＋PDF/HWPX | 韩语 | 法规与标准、包装与标签 |

#### 东南亚

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 18 | `sg_sfa_food_alerts` | P0/一级 | [SFA Food Alerts RSS](https://www.sfa.gov.sg/rss/annual-listing-food-alerts) | RSS＋正文 | 英语 | 食品安全与召回 |
| 19 | `sg_sfa_newsroom` | P0/一级 | [SFA Newsroom RSS](https://www.sfa.gov.sg/rss/newsroom) | RSS＋正文 | 英语 | 法规与标准、原料与技术 |
| 20 | `vn_vfa_news` | P1/一级 | [Vietnam Food Administration](https://vfa.gov.vn/) | HTML 列表＋正文/PDF | 越南语 | 法规与标准、食品安全 |

### 2.2 行业媒体（20 个，首轮暂定）

下表用于当前技术设计和内容结构验证，不代表最终选定。最终 20 个名额从候选池逐个审核，并结合 14 天试跑的抓取成功率、有效独家信号、商业内容占比、重复率、赞助内容比例和访问限制确定。

| # | Source ID | 优先级/等级 | 来源与入口 | 采集方式 | 语言 | 主要分类 |
|---|---|---|---|---|---|---|
| 21 | `media_foodnavigator` | P0/二级 | [FoodNavigator](https://www.foodnavigator.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 产品创新、原料与技术、消费趋势 |
| 22 | `media_beveragedaily` | P0/二级 | [BeverageDaily](https://www.beveragedaily.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 产品创新、消费趋势、企业动态 |
| 23 | `media_foodbusinessnews` | P0/二级 | [Food Business News RSS](https://www.foodbusinessnews.net/rss) | RSS | 英语 | 产品创新、企业动态、零售餐饮 |
| 24 | `media_ift_foodtechnology` | P0/二级 | [IFT Food Technology](https://www.ift.org/foodtechnology/) | HTML 列表；公开元数据和短摘要 | 英语 | 原料与技术、产品创新 |
| 25 | `media_packagingeurope` | P0/二级 | [Packaging Europe](https://packagingeurope.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 包装与标签 |
| 26 | `media_foodbev` | P0/二级 | [FoodBev Media](https://www.foodbev.com/blog) | HTML 列表；公开元数据和短摘要 | 英语 | 产品创新、企业动态、消费趋势 |
| 27 | `media_foodsafetymagazine` | P1/二级 | [Food Safety Magazine News](https://www.food-safety.com/topics/296-news) | RSS 优先，HTML 列表降级 | 英语 | 食品安全、原料与技术 |
| 28 | `media_foodnavigator_asia` | P0/二级 | [FoodNavigator Asia](https://www.foodnavigator-asia.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 亚太产品创新、市场趋势、企业动态 |
| 29 | `media_newfoodmagazine` | P1/二级 | [New Food Magazine](https://www.newfoodmagazine.com/news/) | HTML 列表；公开元数据和短摘要 | 英语 | 原料与技术、食品安全、加工技术 |
| 30 | `media_fooddive` | P0/二级 | [Food Dive](https://www.fooddive.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 企业动态、品牌策略、投融资 |
| 31 | `media_thespoon` | P1/二级 | [The Spoon](https://thespoon.tech/) | HTML 列表；公开元数据和短摘要 | 英语 | 食品科技、零售餐饮、创业公司 |
| 32 | `media_agfundernews` | P0/二级 | [AgFunderNews](https://agfundernews.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 食品科技、投融资、企业动态 |
| 33 | `media_nutraingredients` | P0/二级 | [NutraIngredients](https://www.nutraingredients.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 功能食品、原料与技术、市场趋势 |
| 34 | `media_packagingworld` | P0/二级 | [Packaging World](https://www.packworld.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 食品包装、设备、标签技术 |
| 35 | `media_restaurantbusiness` | P0/二级 | [Restaurant Business](https://www.restaurantbusinessonline.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 餐饮经营、菜单创新、连锁企业 |
| 36 | `media_nissyoku` | P0/二级 | [日本食糧新聞](https://news.nissyoku.co.jp/) | HTML 列表；公开元数据和短摘要 | 日语 | 新品、流通零售、企业动态 |
| 37 | `media_shokuhin` | P0/二级 | [食品新聞](https://shokuhin.net/) | HTML 列表；公开元数据和短摘要 | 日语 | 新品、品牌营销、企业动态 |
| 38 | `media_kr_foodnews` | P0/二级 | [식품저널 foodnews](https://www.foodnews.co.kr/) | HTML 列表；公开元数据和短摘要 | 韩语 | 新品、原料、企业与市场动态 |
| 39 | `media_foodbeverageasia` | P1/二级 | [Food & Beverage Asia](https://foodbeverageasia.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 东南亚原料、设备、企业动态 |
| 40 | `media_apfoodonline` | P1/二级 | [Asia Pacific Food Industry](https://www.apfoodonline.com/) | HTML 列表；公开元数据和短摘要 | 英语 | 亚太加工技术、包装、原料与商业动态 |

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
| 11 | `en_brand_strategy` | 全球/英语 | `(food OR beverage) ("brand strategy" OR portfolio OR premiumization OR localisation)` | 企业动态、消费趋势 |
| 12 | `en_investment_ma` | 全球/英语 | `("food company" OR "beverage company" OR foodtech) (funding OR investment OR acquisition)` | 企业动态 |
| 13 | `en_capacity_expansion` | 全球/英语 | `("food company" OR "beverage company") ("new facility" OR expansion OR partnership OR "innovation center")` | 企业动态、原料与技术 |
| 14 | `ja_product_launch` | 日本/日语 | `食品 新商品 OR 飲料 新商品 OR 食品 開発` | 产品创新 |
| 15 | `ja_ingredient_technology` | 日本/日语 | `食品 原料 技術 OR 発酵 技術 OR 代替たんぱく` | 原料与技术 |
| 16 | `ja_market_retail` | 日本/日语 | `食品 市場動向 OR 小売 新業態 OR 外食 新メニュー OR 食品企業 投資` | 消费趋势、零售餐饮、企业动态 |
| 17 | `ko_product_launch` | 韩国/韩语 | `식품 신제품 OR 음료 신제품 OR 제품 개발` | 产品创新 |
| 18 | `ko_ingredient_technology` | 韩国/韩语 | `식품 원료 기술 OR 발효 기술 OR 대체 단백질` | 原料与技术 |
| 19 | `ko_market_retail` | 韩国/韩语 | `식품 시장 동향 OR 유통 신사업 OR 외식 신메뉴 OR 식품 기업 투자` | 消费趋势、零售餐饮、企业动态 |
| 20 | `en_southeast_asia` | 东南亚/英语 | `("Singapore" OR Malaysia OR Thailand OR Vietnam OR ASEAN) ("food launch" OR foodtech OR investment OR "new facility" OR "retail expansion")` | 产品创新、企业动态、零售餐饮 |

### 3.3 全局过滤与准入

- 默认排除：食谱、家庭烹饪、餐厅点评、个人减肥建议、药品、化妆品、宠物食品，以及与食品加工无关的纯农业资讯。
- `animal feed` 仅在饲料安全、食品链风险或法规标准语境下保留。
- 同一查询每个 provider 最多取 20 条；查询内去重后最多保留 12 条，全部查询合并后再执行全局去重。
- 已列入 40 个直连来源的域名命中发现查询时，与直连记录合并，不重复计入候选。
- 未知域名一律标记为三级。无发布日期、无法回链原文、只有聚合页或疑似软文的结果直接隔离。
- 20 组发现查询默认承担商业和技术线索发现，不替代官方法规与召回监测。
- 商业线索必须找到原始企业公告或至少两个独立可信来源，才能进入 AI 深度分析；只有赞助内容或供应商自述时，可作为“待验证信号”保留，但不得输出确定性市场或技术结论。

## 4. 来源健康与降级规则

- RSS/API：响应 Schema、日期字段和唯一标识写入契约 fixture；连续三次失败后暂停该来源，并在运行报告中列出。
- HTML：使用语义选择器和结构断言，不依赖完整 CSS 层级；页面结构变化时保存脱敏失败样本。
- PDF：优先文本层提取，无文本层时才启用 OCR；HWPX 通过 ZIP/XML 解析，HWP 二进制附件只使用同页 PDF 版本。
- JavaScript 页面：先寻找公开 API 或服务端 HTML；只有条款允许且没有稳定入口时才启用 Playwright。
- 降级顺序：结构化 API → RSS/Atom → HTML 列表 → 同域名 Google News 查询。降级结果仍保留原始来源等级，但在运行元数据中记录采集方式。
- P0 来源任何一个失败不会阻塞简报；P0 连续三次失败会令整次运行标记为 `degraded`，但其他来源和渠道继续执行。

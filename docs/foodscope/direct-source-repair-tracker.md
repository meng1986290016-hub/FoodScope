# FoodScope 人工精选直连来源修复表

状态只在真实读取到近期文章、标题、原文链接、发布日期和正文，并通过自动化测试后改为“已解决”。

| ID | 来源 | 来源包 | 当前问题 / 处理方式 | 状态 | 验证证据 |
|---|---|---|---|---|---|
| M001 | [FoodNavigator](https://www.foodnavigator.com/) | 全球行业、新品 | William Reed 卡片解析、推广过滤、详情正文 | 已解决 | 2026-07-27 探测168小时得11篇；[样例](https://www.foodnavigator.com/Article/2026/07/24/eggcelerator-lab-and-founder-cohort-helps-egg-businesses-grow/)，标题/时间/正文通过 |
| M002 | [Food Business News](https://www.foodbusinessnews.net/) | 全球行业、新品 | 改用官方 [FBN Best News RSS](https://www.foodbusinessnews.net/rss/2) | 已解决 | 2026-07-27 探测168小时得7篇；[样例](https://www.foodbusinessnews.net/articles/30721-the-vita-coco-co-acquires-copra-inc)，标题/时间/摘要通过 |
| M003 | [FoodBev Media](https://www.foodbev.com/blog) | 全球行业、新品 | 改用官方 [Blog RSS](https://www.foodbev.com/blog-feed.xml) | 已解决 | 2026-07-27 探测168小时得20篇；[样例](https://www.foodbev.com/post301/beyond-the-barcode-why-smart-packaging-is-reshaping-the-uk-food-and-beverage-industry)，标题/时间/摘要通过 |
| M004 | [Food Dive](https://www.fooddive.com/) | 全球行业、新品 | 改用官方 [News RSS](https://www.fooddive.com/feeds/news/) | 已解决 | 2026-07-27 探测168小时得10篇；[样例](https://www.fooddive.com/news/nestle-sells-half-water-premium-beverage-business-Peranel/826150/)，标题/时间/摘要通过 |
| M005 | [Just Food](https://www.just-food.com/) | 全球行业 | 尚未核查稳定入口与访问限制 | 待核查 | — |
| M006 | [New Food](https://www.newfoodmagazine.com/news/) | 全球行业 | 新闻页触发 JavaScript 验证；`/news/feed/`、`/feed/` 和公开 WordPress API 均返回 HTTP 202 空正文 | 已移除 | 2026-07-27 按产品负责人要求从生成逻辑及来源包移除 |
| M007 | [Food Manufacture](https://www.foodmanufacture.co.uk/) | 全球行业 | 公开列表 + 详情页 JSON-LD 精确时间和 `articleBody`；增加URL去重 | 已解决 | 2026-07-27 探测168小时得8篇且8个唯一URL；[样例](https://www.foodmanufacture.co.uk/Article/2026/07/24/dairy-firm-withdraws-milk-due-to-possible-presence-of-antibiotics/)，精确时间与正文通过 |
| M009 | [Food Manufacturing](https://www.foodmanufacturing.com/) | 全球行业 | 最近运行HTTP失败 | 待核查 | — |
| M011 | [Prepared Foods](https://www.preparedfoods.com/) | 全球行业 | 最近运行HTTP失败 | 待核查 | — |
| M012 | [IFT Food Technology](https://www.ift.org/food-technology-magazine) | 全球行业 | 更新到现行杂志列表；详情页 JSON-LD 精确时间和正文 | 已解决 | 2026-07-27 探测168小时得4篇，12/12候选日期解析成功；[样例](https://www.ift.org/food-technology-magazine/ashwagandha-gains-traction-as-interest-in-adaptogens-grows)，精确时间与正文通过 |
| M017 | [Food & Drink Technology](https://www.foodanddrinktechnology.com/) | 全球行业 | 新闻卡片、`posted` 日期、详情 JSON-LD 时间及正文 | 已解决 | 2026-07-27 探测168小时得12篇；[样例](https://www.foodanddrinktechnology.com/news/68922/process-complexity-holding-back-innovation/)，精确时间与正文通过 |
| M019 | [BeverageDaily](https://www.beveragedaily.com/) | 原料研发、新品 | William Reed 卡片解析、推广过滤、详情正文 | 已解决 | 2026-07-27 探测168小时得7篇；[样例](https://www.beveragedaily.com/Article/2026/07/23/shandy-shack-unveils-brand-refresh-to-drive-growth-in-fruit-beer-category/)，标题/时间/正文通过 |
| M020 | [NutraIngredients](https://www.nutraingredients.com/) | 原料研发 | 尚未核查；可能复用 William Reed 站群解析 | 待核查 | — |
| M021 | [Food Ingredients First](https://www.foodingredientsfirst.com/) | 原料研发、新品 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M022 | [Nutrition Insight](https://www.nutritioninsight.com/) | 原料研发 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M024 | [Ingredients Insight](https://www.ingredients-insight.com/) | 原料研发 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M026 | [Nutritional Outlook](https://www.nutritionaloutlook.com/) | 原料研发 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M028 | [Dairy Foods](https://www.dairyfoods.com/) | 原料研发 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M030 | [Baking Business](https://www.bakingbusiness.com/) | 原料研发、新品 | 改用官方 [News RSS](https://www.bakingbusiness.com/rss/topic/1227-news) | 已解决 | 2026-07-27 探测168小时得30篇；[样例](https://www.bakingbusiness.com/articles/66636-bimbo-sales-profit-gains-accelerate-in-quarter)，标题/时间/摘要通过 |
| M032 | [MEAT+POULTRY](https://www.meatpoultry.com/) | 原料研发 | 尚未核查；可能复用 Sosland RSS | 待核查 | — |
| M033 | [SeafoodSource](https://www.seafoodsource.com/) | 原料研发 | 尚未核查稳定入口与访问限制 | 待核查 | — |
| M034 | [The Packer](https://www.thepacker.com/) | 原料研发 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M035 | [ConfectioneryNews](https://www.confectionerynews.com/News/) | 原料研发、新品 | William Reed 卡片解析、推广过滤、详情正文 | 已解决 | 2026-07-27 探测168小时得10篇；[样例](https://www.confectionerynews.com/Article/2026/07/24/lindt-sued-over-alleged-child-labour-in-cocoa-supply-chain/)，标题/时间/正文通过 |
| M036 | [DairyReporter](https://www.dairyreporter.com/) | 原料研发 | 尚未核查；可能复用 William Reed 站群解析 | 待核查 | — |
| M039 | [Green Queen](https://www.greenqueen.com.hk/) | 包装加工 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M040 | [FoodHack](https://www.foodhack.global/) | 包装加工 | 尚未核查稳定入口与访问限制 | 待核查 | — |
| M042 | [Packaging Europe](https://packagingeurope.com/) | 包装加工 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M044 | [Packaging Insights](https://www.packaginginsights.com/) | 包装加工 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M050 | [Food Packaging Forum](https://www.foodpackagingforum.org/) | 包装加工 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M055 | [The Grocer](https://www.thegrocer.co.uk/) | 零售餐饮、新品 | 最近运行0候选；待核查付费墙和公开入口 | 待核查 | — |
| M056 | [ESM](https://www.esmmagazine.com/) | 零售餐饮 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M058 | [Supermarket News](https://www.supermarketnews.com/) | 零售餐饮 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M060 | [Grocery Gazette](https://www.grocerygazette.co.uk/) | 零售餐饮 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M061 | [Retail Insight Network](https://www.retail-insight-network.com/) | 零售餐饮 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M063 | [CSP Daily News](https://www.cspdailynews.com/) | 零售餐饮 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M064 | [C-Store Dive](https://www.cstoredive.com/) | 零售餐饮 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M065 | [Convenience Store News](https://csnews.com/) | 零售餐饮 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M075 | [日本食糧新聞](https://news.nissyoku.co.jp/) | 日本、新品 | 改用官方[新闻 RSS](https://news.nissyoku.co.jp/archives/news-cat/001/feed) | 已解决 | 2026-07-27 探测336小时得10篇，标题、日期、摘要通过 |
| M076 | [食品新聞](https://shokuhin.net/) | 日本、新品 | 改用官方 [RSS](https://shokuhin.net/feed/) | 已解决 | 2026-07-27 探测336小时得80篇，标题、日期、摘要通过 |
| M079 | [食品化学新聞](https://www.foodchemicalnews.co.jp/) | 日本 | 改读[食品化学新聞期刊列表](https://www.foodchemicalnews.co.jp/article/fcnhjnewspaper/foodchemicalnewspaper)，详情页提取期号、日期和公开目录 | 已解决 | 2026-07-27 探测15天得2期；10/10候选日期通过，正文1066–1168字 |
| M080 | [ダイヤモンド・チェーンストア](https://diamond-rm.net/) | 日本 | 改用官方 [RSS](https://diamond-rm.net/feed/) | 已解决 | 2026-07-27 探测336小时得10篇，标题、日期、摘要通过 |
| M084 | [健康産業新聞](https://www.kenko-media.com/health_idst/) | 日本 | 改用官方[健康産業新聞 RSS](https://www.kenko-media.com/health_idst/feed) | 已解决 | 2026-07-27 探测336小时得9篇，标题、日期、摘要通过 |
| M085 | [健康産業速報Online](https://www.kenko-sokuho.co.jp/) | 日本 | 放弃陈旧通用Feed，改读当前首页新闻卡片及详情公开正文 | 已解决 | 2026-07-27 探测15天得10篇；20/20日期通过，正文180–585字 |
| M086 | [激流オンライン](https://gekiryu-online.jp/) | 日本 | 改用官方 [RSS](https://gekiryu-online.jp/feed) | 已解决 | 2026-07-27 探测336小时得36篇，标题、日期、摘要通过 |
| M087 | [健康産業流通新聞](https://www.him-news.com/) | 日本 | 改读[最新号列表](https://www.him-news.com/kiji.html)，按期提取主文链接、出版日和详情公开摘要 | 已解决 | 2026-07-27 探测15天得1期；10/10候选日期通过，公开正文375字 |
| M089 | [식품저널 foodnews](https://www.foodnews.co.kr/) | 韩国、新品 | 改用官方 [RSS](https://www.foodnews.co.kr/rss/allArticle.xml) | 已解决 | 2026-07-27 探测336小时得38篇，标题、日期、摘要通过 |
| M090 | [식품음료신문](https://www.thinkfood.co.kr/) | 韩国、新品 | 改用官方 [RSS](https://cdn.thinkfood.co.kr/rss/gn_rss_allArticle.xml) | 已解决 | 2026-07-27 探测336小时得50篇，标题、日期、摘要通过 |
| M091 | [푸드아이콘 FOODICON](https://www.foodicon.co.kr/) | 韩国、新品 | 改用官方 [RSS](https://foodicon.co.kr/rss/allArticle.xml) | 已解决 | 2026-07-27 探测336小时得37篇，标题、日期、摘要通过 |
| M092 | [푸드투데이](https://www.foodtoday.or.kr/) | 韩国、新品 | 改用官方 [RSS](https://www.foodtoday.or.kr/data/rss/news.xml) | 已解决 | 2026-07-27 探测336小时得29篇，标题、日期、摘要通过 |
| M093 | [식품외식경제](https://www.foodbank.co.kr/) | 韩国 | 改用官方 [RSS](https://www.foodbank.co.kr/rss/allArticle.xml) | 已解决 | 2026-07-27 探测336小时得46篇，标题、日期、摘要通过 |
| M094 | [식품외식경영](https://www.foodnews.news/) | 韩国 | 改用官方 [RSS](https://www.foodnews.news/data/rss/news.xml) | 已解决 | 2026-07-27 探测336小时得39篇，标题、日期、摘要通过 |
| M098 | [FoodNavigator Asia](https://www.foodnavigator-asia.com/) | 东南亚、新品 | 尚未核查；可能复用 William Reed 站群解析 | 待核查 | — |
| M099 | [Food & Beverage Asia](https://foodbeverageasia.com/) | 东南亚 | 尚未核查稳定入口与日期字段 | 待核查 | — |
| M105 | [Mini Me Insights](https://www.minimeinsights.com/) | 东南亚、新品 | 最近运行0候选；待核查WordPress Feed与页面结构 | 待核查 | — |

## 第一批验收记录

| ID | 入口验证 | 自动化测试 | 真实近期文章 | 日期正确 | 正文可读 | 最终状态 |
|---|---|---|---|---|---|---|
| M001 | 公开首页 | 通过 | 11篇 | 通过 | 通过 | 已解决 |
| M002 | 官方RSS | 通过 | 7篇 | 通过 | RSS摘要 | 已解决 |
| M017 | 公开首页+详情JSON-LD | 通过 | 12篇 | 通过 | 通过 | 已解决 |
| M019 | 公开首页 | 通过 | 7篇 | 通过 | 通过 | 已解决 |
| M030 | 官方RSS | 通过 | 30篇 | 通过 | RSS摘要 | 已解决 |
| M035 | 公开新闻页 | 通过 | 10篇 | 通过 | 通过 | 已解决 |

## 第二批验收记录

| ID | 入口验证 | 自动化测试 | 真实近期文章 | 日期正确 | 正文可读 | 最终状态 |
|---|---|---|---|---|---|---|
| M003 | 官方RSS | 通过 | 20篇 | 20/20 | RSS摘要 | 已解决 |
| M004 | 官方RSS | 通过 | 10篇 | 10/10 | RSS摘要 | 已解决 |
| M006 | 新闻页、RSS、WordPress API | 不适用 | 0篇 | 不适用 | HTTP 202空正文或JS验证 | 已移除 |
| M007 | 公开列表+详情JSON-LD | 通过 | 8篇，8个唯一URL | 11/11候选 | 通过 | 已解决 |
| M012 | 现行杂志列表+详情JSON-LD | 通过 | 4篇 | 12/12候选 | 通过 | 已解决 |

## 第三批验收记录：日韩来源

| 地区 | 来源 | 入口验证 | 自动化测试 | 真实近期内容 | 最终状态 |
|---|---:|---|---|---:|---|
| 日本 | M075、M076、M080、M084、M086 | 官方RSS | 通过 | 145篇/336小时 | 5个已解决 |
| 日本 | M079、M085、M087 | 当前列表+详情公开内容 | 通过 | 13篇或期/15天 | 3个已解决 |
| 韩国 | M089–M094 | 官方RSS | 通过 | 239篇/336小时 | 6个已解决 |

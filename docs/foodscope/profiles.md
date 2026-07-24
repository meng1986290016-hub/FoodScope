# FoodScope 简报画像

画像决定“同一批事实如何排序和取舍”，不改变原始抓取结果。用户可以切换画像，
也可以复制后自行调整，因此合规人员、研发人员和市场人员无需共用同一种信息
偏向。

## 五个内置画像

| ID | 适合谁 | 主要倾向 |
|---|---|---|
| `balanced` | 管理层、综合情报读者 | 八类主题平衡，并保证一定商业信息占比 |
| `market` | 市场、品牌、战略团队 | 消费趋势、零售餐饮、公司动态 |
| `new_products` | 新品、品牌、创新团队 | 新品上市、产品创新、包装与消费信号 |
| `rd` | 研发、配方、技术团队 | 原料技术、加工包装、科研 |
| `compliance` | 法规、质量、合规团队 | 法规标准、召回与风险预警 |

选择画像：

```json
{
  "foodscope": {
    "profile": "new_products"
  }
}
```

内置文件位于 `data/foodscope/profiles/`。

## 画像字段

- `max_items`：常规简报 15–25 条；
- `max_per_source`：防止单一媒体占据简报；
- `exploration_slots`：为低权重主题保留的探索位；
- `commercial_min_ratio`：综合画像的最低商业信息比例；
- `minimum_score`：常规条目的最低基础分；
- `risk_override_min`：达到该风险级别时进入风险提醒，不受常规分数限制；
- `topic_weights`：八个食品主题权重，总和必须为 `1.0`；
- `market_weights`：目标市场的额外排序权重。

排序基于重要性、画像相关性、商业机会和证据质量，再乘以主题与市场权重。
画像只负责优先级，不会让缺少必要证据的内容绕过准入规则。

## 创建自定义画像

复制最接近的内置画像：

```bash
cp data/foodscope/profiles/market.json data/foodscope/profiles/my_market.json
```

修改其中的 `id`、`name` 和权重，并在配置中使用：

```json
{
  "foodscope": {
    "profile": "my_market"
  }
}
```

也可以把文件放在任意受控路径，并设置 `foodscope.profile_path`。使用
`profile_path` 时不要求文件 ID 与 `foodscope.profile` 相同。

一个偏向中国品牌出海与新品的例子：

```json
{
  "id": "china_brand_launch",
  "name": "中国品牌出海与新品",
  "max_items": 20,
  "max_per_source": 3,
  "exploration_slots": 2,
  "commercial_min_ratio": 0.45,
  "minimum_score": 6.0,
  "risk_override_min": "high",
  "topic_weights": {
    "regulations_standards": 0.08,
    "food_safety_recalls": 0.07,
    "product_innovation": 0.25,
    "ingredients_technology": 0.10,
    "packaging_labeling": 0.10,
    "consumer_trends": 0.18,
    "retail_foodservice": 0.12,
    "company_updates": 0.10
  },
  "market_weights": {
    "US": 0.20,
    "EU": 0.15,
    "JP": 0.10,
    "KR": 0.10,
    "SEA": 0.15
  }
}
```

## 调整建议

一次只改一个维度并连续观察数日：

1. 先换画像，确认内容结构是否更贴近角色；
2. 再调整来源包，修正市场或信息类型覆盖；
3. 最后微调主题/市场权重和最低分；
4. 保留探索位，避免长期被既有偏好锁死；
5. 对高风险提醒和官方证据规则保持谨慎，不用画像权重替代合规判断。

同一运行的规范化、去重与分析结果可以被不同画像复用；多画像产生的只是不同
选择顺序和简报视图。

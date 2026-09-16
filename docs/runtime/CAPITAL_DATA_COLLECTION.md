# 免费资金数据采集与搜索契约 v1

运行编号 CAPITAL-DATA-001。仅改进证据层，不更改 U/O 排名、交易门槛、O 原生输入或历史预测。每日任务时间不变。本机制优先补上此前漏采的南向与港元流动性；不是全部资金身份已经可知。

## 简报准备入口

先核实 HK 交易日与南向是否开放，明确目标完整交易日。每份 AM/PM 简报在形成资金段落之前执行：

```bash
python scripts/collect_hk_capital_evidence.py \
  --target-date YYYY-MM-DD \
  --cutoff YYYY-MM-DDTHH:MM:SS+08:00 \
  --output /persistent-evidence/CAPITAL-YYYYMMDD-AM-attempt1
```

路径是示例，替换为运行环境既有持久证据目录。使用标准库，不需要模型、账号或新环境变量。09:00 使用上一已完成交易日；16:30 当日文件未可用时单独披露原因，并明确标记上一期日期，不能称当日数据。此程序不自行推断节假日或半日市。

读取 receipt.json 的每一项，只有 status=VERIFIED 且 eligible_at_cutoff=true 才能作为该截止的已采集证据。published_at 未知保留 null；first_observed_at 是首次取到当前字节的时间，不冒充官方发布时间或价格时间。本轮晚于早报截止才采到的数据只能追加更正，不能重写早报冻结记录。当前采集器保守要求已在截止前取到；不根据旧日期反推当时已获知。

同一 output 重跑校验原始字节哈希后复用，不再次请求；失败后用新 attempt 目录重试，旧失败不可覆盖。中断且无完整 receipt 的目录隔离留存，新 attempt 继续。不要把 raw 文件或 receipt 的存在当成模型通过。现有 Drive/私密 GitHub 证据保存入口负责持久化整个目录；本 CLI 不自行获得云端写权限。

## 来源登记与成熟度

| 数据 | 主源 | 备用/补充 | 当前状态及限制 |
|---|---|---|---|
| 南向市场买卖额 | HKEX 历史日统计网站数据文件 | 经济通北水日报；AASTOCKS；UBS港股通页 | HKEX自动解析和真实取数通过；备用站点仍需自动适配验收 |
| 南向个股 | HKEX 沪/深通各十大成交股买卖额 | 同上及已有富途只读权益 | 两通道均出现才合并；只出现一通道标部分覆盖；榜外不是零 |
| 港元流动性 | HKMA免费JSON接口 | HKMA官网统计 | HIBOR与总结余已接通；是流动性代理，不是股票机构净流入 |
| ETF申赎 | iShares FXI、KraneShares KWEB发行人 | TraHK、CSOP产品页 | 待实现连续同口径份额序列；不能用成交额或AUM差冒充申赎 |
| 外资/本地机构 | 可核实基金披露、ETF份额及CCASS | 券商公开研究 | 无免费全市场实时身份净流量保证；托管席位不等于最终所有者 |
| 新闻及公告 | 既有香港/欧美新闻管线、HKEX公告 | 经济通、RTHK、FT等已配置源 | 沿用已有管线；本次未重复新建新闻搜索实现 |

官方入口：https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Daily?sc_lang=en
HKMA接口说明：https://apidocs.hkma.gov.hk/documentation/market-data-and-statistics/daily-monetary-statistics/daily-figures-interbank-liquidity/
ETF：https://www.ishares.com/us/products/239536/ishares-china-largecap-etf 、https://kraneshares.com/etf/kweb/
备用：https://www.etnet.com.hk/ 、https://www.aastocks.com/ 、https://warrants.ubs.com/sc/underlying/southbound-moneyflow-turnover

HKEX总体买卖额单位百万港元，十大个股表单位港元，分开解析。总体包含合资格ETF成交，不是O股票池的资金分母。多个网站转发HKEX数据只算来源可用性冗余，不算独立测量。额度余额不能替代实际净买入。美国上市ETF流量不能直接归因美国投资者，更不能全部归因港股。

## 越来越全、快、准的可验证标准

- 全：逐字段登记主源、备用、是否已自动化、实际覆盖分母和缺口；每次优先修复重复失败且影响决策的字段，不因新增网站数量宣称覆盖改善。
- 快：两个独立主源并行；每次连接超时12秒、瞬时故障最多重试一次、单响应上限2MB；同一运行复用已校验缓存。失败源不阻断另一源。记录各源耗时和字节，不承诺免费网站SLA。
- 准：严格检查日期、有限数、币种单位、买卖额合计、通道、哈希及信息截止。截后证据保留但不可用于旧信号；未知不填零。源冲突先隔离，不能取平均凑数。
- 搜索：从官方原件到区域媒体再到社交线索；新闻保留公司关联、发布时间、原文、抓取时间及事实/观点分类。社交内容必须溯源，不自动成为Verified Capital Flow。
- 缺失报告：区分 HTTP/超时、SCHEMA_CHANGED、TARGET_DATE_NOT_AVAILABLE、FIRST_OBSERVED_AFTER_CUTOFF、PARTIAL_CHANNEL_COVERAGE、NOT_PUBLICLY_IDENTIFIABLE。404仅说明未找到，未经核验不直接写未发布。不要把南向已知、ETF未知折叠成整个资金模块UNKNOWN。
- 后续增量验收：ETF发行人连续份额适配、南向自动备用源、跨运行源健康统计及持久缓存复用。未实现项不可标完成。新增数据源不自动改变策略权重；冻结研究保持不动。

## 本轮验收

8项标准库回归测试通过：真实单位及两通道合并、部分通道缺口、错误日期、算术冲突、HKMA代理分类、非有限数与时区、截止与缓存篡改、单源失败隔离。

在线采集2/2主源成功，分别耗时15.140和15.562秒（并发；不将其相加当总时长）。9月15日南向净买入880,670,000港元。首次观察时间为9月16日香港09:35左右，故对09:00旧截止可用数0/2；不回写既有简报。

模型调用0，付费数据调用0，新增API费用0元；平台基础费用不可见。实际收据见 CAPITAL_DATA_001_RESULT.json。尚未实测下一次定时任务自动调用；共用NEXT_ACTIONS与运行说明已登记入口，不等于任务调度已验收。

回滚：撤回本次新增采集器及文档引用，保留所有已冻结证据，不重置账户。中文专项运行契约无现存英文对等版本，本轮未新增英文译本。

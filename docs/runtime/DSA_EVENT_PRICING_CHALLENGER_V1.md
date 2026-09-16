# DSA Event Pricing Challenger v1

状态：**Research Challenger only**。不改变Champion、正式Top3、模拟交易、定时任务或runtime。

## 为什么需要这一层

对于FOMC、CPI、就业、财报等已知时点事件，市场不会等公告发布后才开始反应。期货、利率、汇率、股票和期权会在事件前持续形成预期。DSA因此必须区分：

1. **已经被市场定价的预期部分**；
2. **公告相对预期的真正surprise**；
3. **未来路径/措辞/记者会带来的path surprise**；
4. **央行透露经济信息导致的information/reaction-function effect**；
5. **事件前风险溢价或positioning drift**。

不能把“消息尚未正式公布”简单等同于“市场尚未定价”。

## 研究框架来源

### A. Expected vs Surprise — Kuttner
Federal Funds futures可用于把政策变化拆成anticipated与unanticipated部分；历史研究显示，利率资产对anticipated部分反应很小，而对unexpected部分反应显著。

来源：Federal Reserve Bank of New York, Kenneth Kuttner, *Monetary Policy Surprises and Interest Rates*.
https://www.newyorkfed.org/research/staff_reports/sr99.html

### B. Target + Path — Gürkaynak / Sack / Swanson
FOMC冲击不能只用“本次加/降多少bp”一个因子描述。高频事件研究需要至少区分：
- current target factor；
- future policy path factor。
声明中的未来路径信息对较长期利率尤其重要。

来源：Federal Reserve Board, *Do Actions Speak Louder Than Words?*
https://www.federalreserve.gov/econres/feds/do-actions-speak-louder-than-words-the-response-of-asset-prices-to-monetary-policy-actions-and-statements.htm

### C. Equity sensitivity to surprise — Bernanke / Kuttner
股票市场对未预期政策变化有可测反应；研究估计中，未预期25bp降息平均对应约1%的宽基股指上升。此结果是历史平均敏感度，不应直接当作单次事件预测系数。

来源：Federal Reserve Board, *What Explains the Stock Market's Reaction to Federal Reserve Policy?*
https://www.federalreserve.gov/econres/feds/what-explains-the-stock-market39s-reaction-to-federal-reserve-policy.htm

### D. Pre-FOMC drift — Lucca / Moench
历史上美股在FOMC公告前约24小时存在显著平均超额收益，即pre-FOMC drift。DSA只把它作为事件前风险溢价/positioning context，**绝不把它解释为内幕消息或单次方向确定性**。

来源：Federal Reserve Bank of New York, *The Pre-FOMC Announcement Drift*.
https://www.newyorkfed.org/research/staff_reports/sr512.html

### E. Policy shock vs Information shock — Jarociński / Karadi
公告后窄窗口内：
- 利率↑ + 股票↓：偏hawkish policy shock候选；
- 利率↓ + 股票↑：偏dovish policy shock候选；
- 利率↑ + 股票↑：positive information / reaction-function news候选；
- 利率↓ + 股票↓：negative information / growth-news候选。
这是sign-based研究分类，不是对单次事件的因果证明。

来源：ECB, *Deconstructing monetary policy surprises: the role of information shocks*.
https://www.ecb.europa.eu/pub/research/authors/profiles/peter-karadi.en.html

### F. 2026 Fed综述：reaction-function news与公告外沟通
最新Fed研究综述强调：股票反应不仅来自纯政策shock，还来自reaction-function news、Fed information与communication；对股票而言reaction-function news的重要性尤其值得关注。

来源：Federal Reserve Board, Knox & Vissing-Jorgensen (2026), *The Effect of the Federal Reserve on the Stock Market: Magnitudes, Channels and Shocks*.
https://www.federalreserve.gov/econres/feds/the-effect-of-the-federal-reserve-on-the-stock-market-magnitudes-channels-and-shocks.htm

### G. 市场概率输入 — CME FedWatch
FedWatch以30-Day Fed Funds futures推算FOMC目标利率结果概率。概率是市场定价输入，不是真实世界必然概率。

来源：CME FedWatch methodology.
https://www.cmegroup.com/articles/2023/understanding-the-cme-group-fedwatch-tool-methodology.html

## v1模型结构

### 1. Target Expectation Layer
输入政策结果概率分布，例如：

`{0bp: 7.5%, +25bp: 92.5%}`

输出：
- probability-weighted expected change；
- modal outcome及其概率；
- normalized entropy；
- `TARGET_OUTCOME_DISPERSED / LEAN / LARGELY_PRICED / HEAVILY_PRICED`。

研究默认：modal probability >=80%时，开启`macro_double_count_guard`。
含义是**不能把同一已高度定价目标动作重复当成一份新的事件冲击**；这不意味着高利率水平本身的宏观压力消失。

### 2. Path Expectation Layer
未来路径必须与本次target拆开。若target已经高度集中但path仍分散，则状态为：

`PATH_AND_COMMUNICATION_DOMINANT`

若缺少可验证的path概率分布，则：

`TARGET_PRICED_PATH_AND_COMMUNICATION_UNRESOLVED`

fail closed，不用新闻主观替代概率分布。

### 3. Cross-Asset Pre-Pricing Layer
研究记录：
- 前端利率；
- 美元；
- 股票；
- 期权隐含事件波动（取得时）；
- 事件前已发生的价格移动。

这些只判断“是否存在经典方向的一致预定位”，不直接推断公告后涨跌。

### 4. Pre-Event Drift Layer
若事件前股票已明显移动，可与期权隐含event move比较。

`pre_event_move / implied_event_move`

仅标记positioning/risk-premium context，不能当作“市场提前知道结果”的证据。

### 5. Post-Event Surprise Layer
正式公告后：

`target_surprise = realized_policy_change - pre_event_expected_change`

同时必须将statement window与press-conference window分开，避免把2:00声明与2:30记者会混为一体。

### 6. Joint Shock Classification
用2Y/前端利率与股票窄窗口方向作研究分类：policy shock vs information/reaction-function news。

## 与Intraday Rotation Challenger的连接

Event Pricing作为**context overlay**接入`DSA_INTRADAY_ROTATION_CHALLENGER_v1.1`：

- 不增加sector confirmations；
- 不改变正式信号；
- 当事件target已高度定价时，阻止解释层重复计算同一target风险；
- residual risk继续保留给path、statement、press conference及真正surprise；
- sector relative strength仍必须独立由价格和跨市场数据确认。

因此可能得到：

`MACRO_RISK_OFF + TARGET_EVENT_LARGELY_PRICED + HARDTECH_SECTOR_RISK_ON_CANDIDATE`

而不是简单地“FOMC有风险 → 所有科技都防御”。

## 校准纪律

- v1所有80%/90%概率门槛是Research defaults，不是生产参数；
- 至少回放过去FOMC/CPI/非农/大型科技财报事件，再做未来10-20个事件forward validation；
- 统计false positive、lead time、事件前定价比例、surprise解释力与sector冲突；
- 未经验证不得改变Champion、Top3或交易门槛。

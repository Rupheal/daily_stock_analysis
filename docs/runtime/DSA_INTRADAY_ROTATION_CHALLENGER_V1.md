# DSA Intraday Rotation Challenger v1.1

状态：Research Challenger only。不得改变Champion、正式Top3、模拟交易、定时任务或runtime。

## 目标

识别“宏观仍Risk-Off，但局部高景气硬件/科技板块已经Risk-On”的二维Regime，避免把全市场防御标签机械传导到所有行业。

## 四个观察因子

1. **INTRADAY_SECTOR_RELATIVE_STRENGTH_REFRESH**
   - 09:30 / 10:00 / 10:30优先采样。
   - 记录板块相对基准的bp差，不使用绝对涨跌替代相对强弱。
   - v1研究默认：至少两个快照相对强度 >= 75bp才记确认。

2. **A_SHARE_TO_HK_HARDTECH_LEAD_LAG**
   - A股通信/光通信/半导体相对A股宽基先确认，随后港股对应硬件板块确认。
   - v1研究默认：A股lead >= 75bp且港股存在有效相对强度快照。

3. **PREVIOUS_DAY_WEAK_INDEX_STRONG_SECTOR_PERSISTENCE**
   - 前一交易日指数偏弱但目标板块显著跑赢，次日上午继续相对强时触发。
   - 只记录延续，不把单日反弹直接解释为新趋势。

4. **NEGATIVE_NARRATIVE_REVERSAL**
   - 前期存在明确负面叙事；至少两条相互独立的反向产业/政策/订单证据出现；价格相对强弱同时确认。
   - 新闻条数本身不构成反转，必须与价格确认结合。

## Event Pricing Context Overlay（v1.1新增）

接入`DSA_EVENT_PRICING_CHALLENGER_v1`，用于解释已知宏观事件在公告前被市场预定价的程度。

它**不增加上述四项confirmation数量**，也不直接改变rotation state；只提供：

- `macro_event_double_count_guard`：当目标事件结果已经高度集中定价时，不把同一预期动作再次作为一份新的宏观冲击重复扣分；
- `residual_event_risk`：把剩余不确定性明确留给future path、statement、press conference、真正surprise；
- `target_state`：区分DISPERSED / LEAN / LARGELY_PRICED / HEAVILY_PRICED。

重要：

**“目标动作已经定价” != “宏观压力已经消失”。**

例如FOMC加息高度定价时，10Y收益率5%、高油价、通胀本身仍可保持Macro Risk-Off；只是不能把“可能加25bp”这一已被市场高概率吸收的事件再重复当成新增负面冲击。

因此研究层允许同时存在：

`MACRO_RISK_OFF + TARGET_EVENT_LARGELY_PRICED + HARDTECH_SECTOR_RISK_ON_CANDIDATE`

## 状态机

- `INSUFFICIENT_EVIDENCE`：关键相对强弱/A股lead/前日数据缺失，fail closed。
- `NO_OVERRIDE_CANDIDATE`：不足两项确认。
- `SECTOR_STRENGTH_WATCH`：两项确认，仅观察。
- `MACRO_DEFENSIVE_SECTOR_RISK_ON_CANDIDATE`：宏观Risk-Off仍成立且至少三项确认；允许把研究标签拆分为“宏观防御 / 局部板块Risk-On候选”。

所有状态均：
- 不修改Champion；
- 不生成正式BUY/SELL；
- 不修改Top3；
- 不激活runtime；
- 不改变现有模拟或真实交易门槛。

## 校准边界

v1/v1.1的75bp、2快照、2条反向证据以及Event Pricing的80%/90%概率阈值均是显式Research defaults，不是生产校准参数。必须至少观察10个未来港股交易日，优选20个，并同时回放历史FOMC/CPI/非农/大型科技财报事件，统计：

- rotation recall；
- false-positive rate；
- 首次识别lead time；
- 与原Champion冲突次数；
- 冲突后1/3/5交易日板块相对收益；
- 事件前已定价比例与公告surprise之间的关系；
- 哪个因子在不同市场Regime下失效。

在完成forward validation前，不允许用单日案例直接调Champion权重。

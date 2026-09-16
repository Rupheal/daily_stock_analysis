# DSA Intraday Rotation Challenger v1

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

v1的75bp、2快照、2条反向证据等均是显式Research defaults，不是生产校准参数。必须至少观察10个未来港股交易日，优选20个，统计：

- rotation recall；
- false-positive rate；
- 首次识别lead time；
- 与原Champion冲突次数；
- 冲突后1/3/5交易日板块相对收益；
- 哪个因子在不同市场Regime下失效。

在完成forward validation前，不允许用今天这一例直接调Champion权重。

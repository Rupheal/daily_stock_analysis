# O native target session rule v1

状态：FROZEN / MODEL-FREE / GENERAL RULE

目的：定义 O native 在“跨自然日但尚未产生新的完整交易日”时如何选择 daily-bar target session。该规则与模型结论、Top3、O 全池、U 模型无关。

## 1. 权威时间轴

- 市场：Hong Kong / XHKG
- 时区：Asia/Hong_Kong
- `target_session` 的定义不是“当前自然日”，也不是“数据供应商最新返回日”，而是：

> 在评估时点已经完成官方 regular session close 的最近一个 XHKG trading session。

等价规则：

1. 港股交易日开盘前、盘中、午休、收市竞价结束前：target = 上一个已完成交易日；
2. 港股交易日官方 regular close 之后：target = 当日；
3. 周末/假期/非交易日：target = 上一个已完成交易日；
4. 仅跨过香港午夜不会改变 target；
5. 只有新的 XHKG regular session 真正收盘，target 才能向前滚动。

## 2. 自然日跨越规则

例：

- 2026-09-15 收盘后：target = 2026-09-15；
- 2026-09-15 23:59 HKT：target = 2026-09-15；
- 2026-09-16 00:03 HKT：target 仍 = 2026-09-15；
- 2026-09-16 开盘前/盘中：target 仍 = 2026-09-15；
- 只有 2026-09-16 regular close 完成后：target 才 = 2026-09-16。

因此：

> `calendar_date != target_session` 是正常状态，不能据此把 target 改成自然日。

## 3. target 与 provider query boundary 必须分离

`target_session` 是投资/验收语义；provider 的 `start/end` 只是取数 API 边界。

以 yfinance daily 为例，其 `end` 为排他边界。若目标 target_session = 2026-09-15，则允许使用：

- provider query end-exclusive = 2026-09-16

但：

- target_session 仍是 2026-09-15；
- 不得把 query end 误解释成 target；
- 返回数据的 latest complete daily bar 必须精确等于 target_session。

通用要求：

- inclusive provider：可按 provider 契约使用 target 本身；
- exclusive-end provider：使用 target 后一个 calendar day 作为 retrieval boundary；
- provider boundary 绝不改变 target-session 语义。

## 4. 数据成熟度规则

exchange calendar 决定“应该分析哪个完整 session”；provider 决定“这个 session 的数据是否已经可取得”。二者必须分开。

如果 calendar target 已经是 T，但 provider 暂时只返回 T-1：

- 状态 = `TARGET_DATA_NOT_MATURE`；
- O native = WAIT / NO MODEL CALL；
- 不允许把 target 静默回退到 T-1；
- 不允许把 stale bar 冒充 T；
- 不允许通过改时区、改日期标签或放宽 same-session gate 解决。

## 5. Run 内冻结规则

每一个受控 O-native run 在进入正式 preflight 时冻结：

- `evaluation_time_hkt`
- `target_session`
- `target_session_source = XHKG_COMPLETED_SESSION`
- `calendar_version/provider_contract_version`

同一 run 内 target 不得静默改变。

如果 run 等待期间产生了新的完整 XHKG session：

- 原 run 状态 = `TARGET_SESSION_STALE_AFTER_NEW_CLOSE`；
- 原 run 不得继续调用模型；
- 必须开启新的受控 run / 新 preflight；
- 原证据保留，不覆盖。

## 6. CLAIM / recovery 特别规则

zero-HTTP recovery 的 successor 必须保留原 CLAIM/native artifact。

若 recovery 原 CLAIM 针对 target T：

- 只要 `latest_completed_session == T`，允许继续对 T 做受控 recovery；
- 仅跨自然日、开盘前或盘中，不会使 recovery 失效；
- 若已经出现新的完整 session T+1，则旧 recovery 不得静默滚动到 T+1；
- 状态 = `RECOVERY_TARGET_EXPIRED_NEW_COMPLETED_SESSION`；
- 如需分析 T+1，必须新建新的受控验收链，不得复用旧 CLAIM 当作 T+1 授权。

## 7. Fresh preflight 定义

`fresh` 指“在当前 retrieval_time 重新获取并验证 target_session 所需证据”，不是“target 必须等于当前自然日”。

Fresh preflight 必须同时满足：

- target 按本规则解析；
- primary / independent price sources latest validated complete bar == target；
- native data-only smoke latest bar == target；
- observer context date == target；
- OHLC/volume 继续使用已冻结 input contract；
- 新闻/公告 freshness 使用各自 retrieved/available time，不得反向改变 price target。

## 8. Fail-closed 状态码

- `TARGET_SESSION_UNRESOLVED`
- `TARGET_DATA_NOT_MATURE`
- `TARGET_SESSION_STALE_AFTER_NEW_CLOSE`
- `RECOVERY_TARGET_EXPIRED_NEW_COMPLETED_SESSION`
- `NATIVE_TARGET_SESSION_MISMATCH`
- `PROVIDER_BOUNDARY_TARGET_CONFUSION`

出现以上任一状态：

- model_http_requests = 0
- 不生成正式 O Top3
- 不进入 O 全池
- 不修改 canonical CLAIM/native evidence

## 9. 当前 Run018 适用结论

在 2026-09-16 00:03 HKT，尚未产生 2026-09-16 的完整 XHKG session，因此：

- 正确 target_session 仍应为 2026-09-15；
- 不能因为自然日变为 2026-09-16 就把 target 改成 2026-09-16；
- yfinance 为取到 2026-09-15 bar 可以使用 exclusive end=2026-09-16；
- 若 fresh preflight 在此时无法重新确认 target=2026-09-15，则应诊断其 freshness/news/issuer/price gate，而不是改 target 语义；
- 若等到 2026-09-16 regular close 后仍未执行 recovery，则旧 2026-09-15 recovery target 应过期，不得静默升级。

## 10. 冻结原则

本规则只定义 session semantics，不授权模型请求，不授权 successor，不修改 main，不修改 Run008，不修改 O/U Universe。

Accepted Progress 仅限：target-session contract 被明确定义并可用于后续 model-free tests。
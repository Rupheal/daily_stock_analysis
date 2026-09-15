# RUN018 FINAL｜零HTTP恢复机制建立；successor在Fresh Preflight阶段fail-closed

Run ID：TRI-DSA-EXEC-20260916-018

## 最终状态

- 分支：`fix/native-private-execution-20260914`
- 冻结上游：`089d9d26d68f8b839ea5a74a3784e4402925f8b7`
- 最新Owner recovery authorization：存在，最多允许1次successor HTTP，但仅当全部硬门槛同窗PASS
- canonical O arm：false
- fallback：不得使用
- Drive：4/4 PASS仍有效
- canonical CLAIM：保留，不删除、不覆盖
- canonical native failure artifact：保留并已验证
- zero-HTTP recovery policy：已建立
- shared native input / volume reconciliation contract：已建立
- model-free observer/recovery tests：30/30 PASS
- read-only zero-HTTP eligibility：PASS；canonical evidence可恢复，原请求数0
- successor workflow：Run 34989320785 / Job 104449530443
- successor最终：FAIL_CLOSED_AT_FRESH_PREFLIGHT
- 本Run DeepSeek HTTP requests：0
- 本Run DeepSeek tokens：0
- 本Run DeepSeek增量模型费用：0 CNY
- O single formal acceptance：仍未PASS
- O Top3：不可正式使用
- U formal：0/45
- simulation：NOT_ELIGIBLE / WAIT
- fixed legacy：仍12/16=75%

## 已完成的Accepted Progress

1. Run017 canonical CLAIM/native artifact只读reconciliation完成，证明模型HTTP请求为0。
2. 建立`o_zero_http_recovery_policy.py`，明确claimed-but-zero-HTTP不能删除旧CLAIM，只有显式Owner授权且全部门槛通过才允许最多1次append-only successor。
3. 建立共享`o_native_input_contract.py`并将observer从旧0.5-share绝对门槛迁移到冻结的session/OHLC/volume reconciliation契约。
4. 成交量契约继续保持shares单位、错误session fail、100x/0.01x fail、超校准边界fail，不为小米硬编码放宽。
5. model-free observer/recovery tests 30/30 PASS。
6. 识别Run017真正session根因：冻结Yfinance路径的`end`为排他边界；此前目标2026-09-15时，end=2026-09-15只能得到2026-09-14，end=2026-09-16才可含2026-09-15。
7. Owner授权已记录为append-only recovery authorization，不修改canonical CLAIM。
8. successor执行前完成owner/frozen-state、30/30 tests、canonical reconciliation、fresh unique Drive roundtrip等门槛。

## successor失败点

Run 34989320785在等待Asia/Hong_Kong跨入2026-09-16后继续执行。

已PASS：
- explicit owner authorization / frozen-state gate
- natural HK date boundary wait
- deterministic/frozen runtime dependencies
- observer and zero-HTTP recovery regressions
- canonical private evidence reconciliation + owner authorization
- fresh unique Drive save/read/SHA/restore

随后：
- `Fresh complete Xiaomi independent preflight` = FAIL

因此以下全部SKIPPED：
- frozen-native same-window data-only smoke
- observer exact-session contract against frozen native DB
- successor child/claim absence check
- DeepSeek balance check
- successor durable child call-intent
- successor HTTP request
- successor raw evidence save
- post-call usage
- semantic acceptance

所以不能称发生过successor model call。

## 为什么本Run在这里停止

workflow对fresh preflight要求仍冻结为：
- `passed=true`
- `prices_passed=true`
- symbol=HK01810
- target=`2026-09-15`
- prices=`passed`
- news=`passed_limited_coverage`
- issuer=`listing_passed_body_incomplete`

跨日后的fresh preflight没有满足上述完整断言，但现有公开step summary不能安全证明究竟是哪一个字段发生了变化。任何自动把target改为2026-09-16、放松news/issuer状态、或跳过fresh preflight都会改变验收语义。

按照Owner指令：只要需要解释性判断，就不调用模型并停在恢复状态。因此本Run不修改target、不重跑successor、不消耗DeepSeek请求。

## 下一最小自然动作

只读检查新的fresh preflight输出与日期语义，明确失败字段：
1. 当前fresh preflight target究竟是2026-09-15还是2026-09-16；
2. 价格/新闻/issuer中哪一项状态改变；
3. 对于跨自然日但港股尚未产生新完整交易日的时点，验收target应定义为“最新完整港股交易日”还是固定原CLAIM交易日；
4. 不得靠修改workflow常量来让测试通过；必须先冻结一条通用session policy并以model-free证据验证。

在该session policy正式验收前：
- recovery authorization不等于可立即请求模型；
- successor HTTP requests继续为0；
- 不允许重新使用Run 34989320785；
- 不允许创建新的child claim；
- 不允许O全池。

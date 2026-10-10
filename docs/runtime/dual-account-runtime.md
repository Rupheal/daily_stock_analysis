# 双模型模拟运行入口 v1（2026-09-14）

## 2026-09-26 隔离候选：不可变信号契约

此变更仅为工程候选，不切换 Runtime、不修改历史 journal、不代表真实周期验收。

- O 的 official/operational 分母必须是当前正式回执中的正整数，且 operational 不大于 official；不再把 660/657 当作永久常量。生成型正式回执且 missing_count=0 时，覆盖数使用该 operational 分母；无当期排名的 WAIT 覆盖数为 0。U 保留 45 分母，覆盖数读取 formal_valid_rows。
- 回执必须携带不可变 `signal_timing` 对象，含带时区的 `cutoff`、`available_at`、`valid_until`，及 `next_session`。这些字段必须来自经过核验的正式生产/发布证据；本模块只校验契约，不能证明其权威性。不得由重试时钟、文件修改时间或计划时刻补造。
- 验证顺序为 cutoff ≤ available_at ≤ valid_until；执行时刻不得早于 available_at 或晚于 valid_until，next_session 必须与已验证会话路由一致。过期信号不能通过重试延长有效期。
- SIGNAL 的 at 固定为源 available_at；生成报告的 generated_at 仍为本次执行时刻。命令来源使用内容寻址的 sha256 引用，同一回执原始字节跨工作目录、跨重试生成完全一致的命令。
- 缺少时间、分母、覆盖证据或输入对象与磁盘原始字节不一致时，该轨进入 BLOCKED 且不输出 SIGNAL/ENTRY。不得仅为恢复旧行为而填充元数据。
- 现有历史正式回执没有完整 signal_timing；未在本次变更中补写或重新验收。生产者提供独立验证的完整时间证据、正式 CI 与 Alienware 验证通过、Owner 批准后，才能考虑部署此候选。
- 原有同 ID 内容漂移拒绝保持不变。若历史 journal 已有旧构造方式的命令，同 ID 新内容仍会被拒绝；不得改写旧账本、换 ID 重复入场或静默跳过冲突，必须进入单独的迁移审查。
- 当前仅验证纯离线编排/解析及真实账本模块的 synthetic 回归，不代表真实行情、Drive 持久化、Entry hook 部署或真实 Shadow Cycle 通过。未新增环境配置项，英文专题文档未同步，因为本次修改的是这份现有中文运行契约；代码和测试说明保持英文。

回滚：部署前直接弃用候选代码；若未来获批部署，回滚代码时仍保留全部 journal 历史与原有冲突校验。

## Run013实现接续

实际43号工作流已改为Drive原始字节保存；44号只作离线及合成恢复准备。OAuth缺失时不调用模型。限定授权操作见 `DRIVE_OWNER_SETUP.zh-CN.md`。既有私密GitHub脚本保留作备选；ESSD R本批无复制回执，NAS待接入；权威账本保持原ID。下列旧Run009/Run012说明按历史证据保留，不代表当前存储执行路径。

## 2026-09-14 最新用户覆盖：Drive 优先，U 准备独立推进

用户已明确要求立即执行以下调整；本节覆盖旧的存储优先级和 U 准备串行限制。
- Google Drive 为原始证据首选保存位置；使用已有 TRIDENT_BACKUP 下的 DSA_PRIVATE_EVIDENCE。目标文件夹已经连接器元数据核验为未共享、仅 owner 权限；具体 ID 保留在私密配置中，不写公开仓库。
- GitHub 保留代码和脱敏验收摘要；Run011/Run012 已有私密 GitHub 有界文本保存工程及证据完整保留，降为备选。DSA_EVIDENCE_TOKEN 不再是 Drive 主路径的必需配置，不要求 Owner 为首选方案先配置它。
- Drive 连接器可访问文件夹不等于 GitHub runner 已获得 Drive 授权。必须验证 runner 身份、最小访问权限、原始字节上传/读取/SHA-256 一致性；ZIP/JSON 等保留原格式。连接器探针不能代替 runner 验收。
- 禁止经公开 GitHub 日志或附件中转原始模型内容；不导出连接器凭据或模型密钥，不在聊天索取密钥。
- O 存储等待期间，U45 的身份、当期沪深港股通并集买入资格、停牌、复权、量单位、新闻公告、资金数据和时间戳核验独立推进；复用 Run009 收据，失败保留在45分母中，不重复全池抓取。
- 此次解除的仅是 U 独立准备等待 O 的限制；正式模型验收、合格 BUY、完整费用/汇率/整手及发布后价格等信号和模拟门槛不变。
- NAS 仅作未来第二份独立备份，目前未接入，不作为前置条件。不新增订阅或购买服务。
- 日常简报继续报告实际状态；不修改定时任务、main、历史预测或权威模拟账。
- 外部配置不足时立即给出具体缺口及下一动作，不重复同一检查空等；常规独立准备继续推进。

本次调整是执行政策与接续清单更新，不代表 Drive runner 保存、O 原生报告或 U 正式验收通过。


本模块是独立模拟执行层，不修改O原版代码、提示词、评分或原生买卖结论。不执行网络请求、模型调用或真实订单。

## 权威与边界

代码分支：`fix/dual-account-runtime-20260914`。继承父提交：`456a08bfc8cccc99b3b0edf1f59643b6e379a43a`。
用户最新授权仅更新现有DSA任务说明，保持原任务时点，不创建任务，不合并main。必要DeepSeek研究按现有余额执行，禁止自动充值、新付费订阅及敏感内容公开导出。

账户配置和可写journal在用户的持久文件中；不提交公开仓库。测试数据全部是synthetic-fixture。现有看板DEV Seed不是正式成交账，旧研究影子组合不能迁入本账户。

## 资金数据准备（2026-09-16增量）

形成资金段落前按 [免费资金采集契约](CAPITAL_DATA_COLLECTION.md) 执行只读采集。逐项读取 receipt 的来源、日期、截止资格和缺失原因；已有南向事实不得与身份不可识别项合并成全模块UNKNOWN。此步骤不改变交易门槛或O原生逻辑，下一次定时消费仍待真实验收。

## 2026-09-18 O unresolved-symbol exclusion policy

User directive: unresolved O-universe members must not trigger repeated rescue loops. The official HK Connect universe remains the audit universe, while O ranking/formal acceptance uses a separately reported operational denominator.

Authoritative policy: `docs/runtime/O_UNRESOLVED_EXCLUSION_POLICY.json`.

Rules:
- Keep the full official universe for audit/reconciliation; do not erase a failed or unresolved member from history.
- A normal current-session refresh may be followed by at most one additional model-free confirmation cycle for a symbol. If status still cannot be verified, mark it `EXCLUDED_UNRESOLVED_FOR_SESSION`.
- Do not use paid model calls to rescue data/status ambiguity, and do not launch repeated bespoke recovery jobs for the same symbol/session.
- Excluded unresolved symbols do not block O formal acceptance and are removed from the operational ranking denominator for that session.
- O acceptance coverage is measured against the operational denominator; audit reconciliation must still satisfy: ranked/accepted operational members + explicit exclusions = official universe.
- Re-entry is passive: on a later session a symbol can return only if the normal refresh itself yields a clear verified status. Do not special-rescue it merely to restore the denominator.
- For the 2026-09-18 session, 00853 / 02172 / 02252 are excluded from the operational O pool. Official denominator remains 660; operational/formal denominator becomes 657. No further rescue attempts are authorized for those three for this session.

## 一次运行

1. 读取最新 `DSA_DUAL_ACCOUNT_JOURNAL.json`，保留其文件ID、version及下载时哈希。已有账户找不到时禁止重新初始化，应恢复原件。
2. checkout本分支已验收提交。运行前核验 `docs/DSA_NEXT_ACTIONS.json`，查找新增有效产物；不重新消费已经冻结的模型请求。
3. 构造带来源、sha256、时间的commands。先处理上轮待执行信号的价格路径，再处理本轮新信号；禁止把过去的成交追加到较晚命令前面。
4. `PYTHONPATH=. python scripts/dsa_simulation_runtime.py --journal <journal.json> --commands <commands.json> --summary <summary.json>`
5. 以原文件ID和expected_current_version替换保存journal。发生版本冲突，重新下载原件、重放未处理命令再保存；禁止取消版本检查或last-write-wins。成功保存后才发布summary；报告注明journal哈希。
6. 周报执行相同CLI但不传commands，直接复算账本，禁止从简报自由文本猜测成交。

## 命令契约

通用字段：id、account(U/O)、at(带时区)、kind。id按模型、信号、事件生成，重跑相同id同内容为no-op，改变内容拒绝。journal为哈希父链，原始信号不可追写。

- SIGNAL：signal含id/cutoff/available_at/scope=forward_simulation/passed/reason。通过时还须来源及哈希、covered/denominator、data_news_plan_verified、top3、next_session、valid_until；O须engine=original_native_dsa及冻结upstream_commit。U45/O独立官方并集，不得自造分数；O排名必须100%覆盖当期 operational denominator；official denominator 仍按“有效排名 + 明确排除项 = 官方全集”对账。U保留45分母且允许逐股验收通过的合格候选，其余隔离。
- ENTRY：signal_id/code/quote/fee_cny/excluded。quote须raw价格、执行时间、HKD→CNY汇率及证据、整手及来源，验证first_eligible_price；日线模式须确认下一实际交易日open。较高名次被排除须给出证据。每信号最多一个新仓，已持仓跳过；不加仓。费用未知时不新开仓。
- MARK：当前持仓逐一给可核验报价及汇率；缺标记不假算NAV。当前版采用同一估值时点，异步报价需上游先建立已验证的统一快照。
- BAR：原始OHLC及开闭市时间、企业行动/停牌、汇率来源；每个价格区间仅处理一次。跳空止损按开盘更差价；日线止损与止盈同现先止损；达到首次止盈后无法判定保本线先后时保守退出并留痕。企业行动未实现的转换保留隔离，不虚构拆股或分红。
- RANK：完整可比较快照、rank/score及信号。缺股票排名、数据失败或不同比较口径标UNKNOWN，不计连续跌出；Runner严重衰减仅在下一可交易价格退出，不能用言论/排名出现前的开盘价。

所有价格、费用与汇率的verified标记均必须由外部证据验收产生，不能为让测试通过手工标true。模块能校验结构、时序及算术，不能证明来源本身真实。

## 已确认纪律及保守实施解释

配置由用户私有账户记录承载：双账户相同初资、单票/总仓/行业上限，最多3仓；初始-2%，+5%卖初始数量1/3，+10%再卖1/3，余量Runner；+20%起每10%仅复核；无额外time stop。中度评分衰减取已确认10%-15%范围下端10%仅预警；严重20%并排名恶化才触发。至少3整手才允许开仓，两个止盈段各向下取整到整手，余额归Runner。该取整是执行解释，后续变更必须版本化。

原生O的观察/卖出不能被Top3排名覆盖成买入。模拟B+C是共同执行层，不称为O原生退出建议。两池不同，比较为整体系统比较，不能归因纯算法。

## 本次真实状态

Run006 `34805328127` 的artifact SHA256已校验：O日线feature_ready638/660，22隔离；不是638个原生模型结果。2026-09-14早报两轨均不具可执行信号，接入为WAIT，零买卖。
O全池原生模型输出、U完整新闻/资金/交易计划、正式未来成交和周报触发仍待验。前端runtime_bundle.js及app.js未找到可访问原件，看板联动待验，不修改该界面或其本地真实账户。

## 测试及恢复

`python -m pytest --noconftest -q tests/test_dsa_simulation_ledger.py tests/test_dsa_prediction_ledger.py`
此入口只检验独立纯Python模块，无服务依赖；未运行全仓测试。19个测试含跳空、同日先后不明、重复事件、篡改、CAS冲突、Rank Decay、缺排名、价格重叠和O身份边界。
本地保存采用锁、临时文件和原子替换；远端必须另用版本CAS。恢复使用最后一份已持久化journal重放，保留失败和WAIT，不删除旧记录。回滚代码提交须保留原journal配置及历史；不得把回滚代码当作重置账户资金。

# 双模型模拟运行入口 v1（2026-09-14）

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

## 一次运行

1. 读取最新 `DSA_DUAL_ACCOUNT_JOURNAL.json`，保留其文件ID、version及下载时哈希。已有账户找不到时禁止重新初始化，应恢复原件。
2. checkout本分支已验收提交。运行前核验 `docs/DSA_NEXT_ACTIONS.json`，查找新增有效产物；不重新消费已经冻结的模型请求。
3. 构造带来源、sha256、时间的commands。先处理上轮待执行信号的价格路径，再处理本轮新信号；禁止把过去的成交追加到较晚命令前面。
4. `PYTHONPATH=. python scripts/dsa_simulation_runtime.py --journal <journal.json> --commands <commands.json> --summary <summary.json>`
5. 以原文件ID和expected_current_version替换保存journal。发生版本冲突，重新下载原件、重放未处理命令再保存；禁止取消版本检查或last-write-wins。成功保存后才发布summary；报告注明journal哈希。
6. 周报执行相同CLI但不传commands，直接复算账本，禁止从简报自由文本猜测成交。

## 命令契约

通用字段：id、account(U/O)、at(带时区)、kind。id按模型、信号、事件生成，重跑相同id同内容为no-op，改变内容拒绝。journal为哈希父链，原始信号不可追写。

- SIGNAL：signal含id/cutoff/available_at/scope=forward_simulation/passed/reason。通过时还须来源及哈希、covered/denominator、data_news_plan_verified、top3、next_session、valid_until；O须engine=original_native_dsa及冻结upstream_commit。U45/O独立官方并集，不得自造分数；O全池排名必须全覆盖；U保留45分母且允许逐股验收通过的合格候选，其余隔离。
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

Warning: truncated output (original token count: 62094)
Total output lines: 2393

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases) page.

## [Unreleased]

- [修复] 港股报告复核将止损注释中的即时离场阈值纳入一致性检查，并拦截有限新闻检索推导“无利空”、未核验基本面方向及虚假实时行情来源；增加第二次真实输出的无模型回放。

- [测试] 经授权追加一次小米修复后验收；模型前确认未核验财务块已隔离，失败报告即使未入历史库也保留原始响应、拦截前后结果及用量证据。

- [修复] 小米真实模型输出回放发现跨段止损与主入场价冲突、监管状态过度确定及未核验财务数值；港股隔离财务聚合输入、补充报告拦截并撤下失败报告的执行字段，保留真实反例测试，不追加模型调用。

- [修复] 小米单股验收重新抓取并核对独立行情和区域新闻；模型前复核输入、限制一次API请求并留存原始用量；港股提示补充K线与量比核对值，止损审计按明确入场价区分股票和账户风险。

- [改进] 港股新闻默认改为香港、美国和欧洲来源；加入经济通公司新闻与官方RSS、香港电台及FT RSS；过滤旧大陆来源和不明转载，保留原媒体署名及失败诊断。

- [测试] 公共媒体探测增加受信HTTPS代理对照、响应耗时与字节统计及错误脱敏；正式资讯DNS保护保持不变。

- [修复] 接入富途与新浪公开个股新闻，校验公司与发布时间；港股优先腾讯和东方财富并跳过缺失日线；报告复核接入保存及通知前。

- [修复] 单股验收增加模型输出数值复核，拦截量比口径、K线几何及止损距离矛盾；51项相关测试通过，实证回放不增加模型调用。

- [修复] 腾讯日线支持港股并正确处理成交量与成交额单位；港股资讯池不再将无关市场资讯计作个股证据。
- [测试] 新增小米已核验输入的单次验收，交叉校验完整日线和时效，记录余额及结果；49项相关测试通过。

- [测试] 增加隔离 OpenBB 4.7.2 与腾讯、新浪、原生新闻的只读小米验收；不配置模型密钥，不调用模型。

- [修复] 新增修复分支小米验收入口，显式开启原生免费资讯池自动采集，执行当前分支代码并保存失败证据；无定时触发。

- [修复] 独立修复版采用完整日线分析，阻止未标时实时报价覆盖历史 OHLC/指标；在两条分析路径前校验交易日与 OHLC，修正缺失新闻的提示语义。

- [chore] 添加小米单股手动验收，使用官方 DeepSeek 与固定原版 DSA，保存原生报告和用量。

- [chore] 新增手动云端环境检查：固定上游版本，验证依赖、CLI 和模块导入，不调用模型。

- [测试] 修复股票名称解析冷启动超时并发测试的同步竞态：在放行后台抓取前确认两个等待者均已结束并返回空结果，避免 Docker 发布门禁偶发失败。

<!-- 新条目格式：- [类型] 描述（类型取值：新功能/改进/修复/文档/测试/chore）-->
<!-- 每条独立一行追加到本段末尾，无需分类标题，合并时冲突最小 -->

## [3.32.0] - 2026-09-06

### 发布亮点

- feat: 已登记 A 股指数贯通 Web/API、Bot、CLI 与 GitHub Actions 分析入口，注册表扩展至 33 项，并统一指数身份、任务去重、历史与 Chat 上下文。
- feat: 新增个股研究聚合 API、ResearchArtifact 结构化研究产物，以及数据源能力与数据集质量只读接口。
- feat: 完善 Futu OpenD 港股数据源接入，新增 Web Chat 分词基础模块与 Agent 轨迹评估入口。
- feat: 自建 SearXNG 搜索超时可配置，Tavily 改用 basic 搜索以降低 credit 消耗。
- fix: 定时分析采用独立进程与硬超时保护，选股结果支持历史恢复，桌面端增加全局更新入口，并修复 Linux/Docker 分享图中韩文字体缺失。
- fix: 收敛 LiteLLM 兼容版本窗口，更新 Web/桌面依赖，并修复美股数据源优先级与股票名称归一问题。

### 变更明细

- [修复] 入口分类的模式边界修复（PR3 review）：不消费个股列表的模式（`--backtest`/`--market-review`/`--serve-only`/`--webui-only`/`--portfolio`/`--schedule`/`config.schedule_enabled`）在模式分发前整体跳过 `--stocks` 与 GitHub Actions `STOCK_LIST` 的分类与索引刷新，未登记 `.CSI` 等坏 token 不再拦截这些模式（此前 `GITHUB_ACTIONS=true` 下 `--backtest`、`--portfolio futu`、`--schedule` 配坏 watchlist 会在进入模式主体前被整批拒绝）；`--schedule --stocks` 的"警告后忽略启动快照"语义保留；`--stocks` 与 GitHub Actions 入口的指数分类与整批拒绝契约不回归，文档同步把指数自选股配置收窄为仅这两类入口（本地 `.env`/Docker 无参数默认运行保持股票语义，分析指数请配 `--stocks`）。
- [新功能] 指数注册表新增国证粮食（`sz399365`）与中证钢铁（`csi930606`）：已登记 seed（`scripts/stock_index_seeds/index_registry.csv`）与 bundled 指数清单（`apps/dsa-web/public/stocks.index.json`）由 31 项扩展到 33 项，已登记指数的 `sh`/`sz`/`csi` 前缀与 `.SH`/`.SZ`/`.CSI` 显式形态均可作为自选股指数目标；ETF 与美股指数不进 CN 注册表，路由语义不变。
- [文档] 中英 full-guide 新增「指数自选股配置」小节：说明已登记指数前缀/显式后缀规则、未登记 `.CSI` 整批拒绝、裸码不自动提升为指数、NDX 等美股指数裸码即正确路由、ETF 走股票路径，并同步补充 README / DEPLOY 的 `STOCK_LIST` 提示；修正 full-guide 中已过期的「已登记 5 个沪深指数」表述。
- [新功能] GitHub Actions 每日工作流支持已登记指数入口：`GITHUB_ACTIONS=true` 下无参数 `python main.py` 把 `STOCK_LIST` 按与一次性 `--stocks` 相同的判型规则分类为结构化 target（显式指数 token 进入指数路径、个股 token 保持既有 legacy 路径），指数与个股同批复用同一 Pipeline，不新增第二条能力矩阵；本地与 `--schedule` 热刷新默认路径不在入口构造 target，语义不变。
- [修复] `main.py --stocks` 对未登记 `.CSI` 目标在入口明确报错并整批拒绝本轮运行（此前被静默按股票 token 交给 provider），拒绝发生在任何 provider 请求之前，与 API 层"provider 调用前明确拒绝"的边界对齐；CLI/Actions 整批拒绝与 API 异步批量仅拒绝该目标的差异已在文档中说明。
- [测试] 新增 Bot 指数入口 transport-independent 在线 E2E smoke（`scripts/smoke_bot_index_entry.py`）：worker 子进程经真实 `CommandDispatcher.dispatch_async` 提交并在同进程轮询 `TaskService` 贯穿到 `StockAnalysisPipeline`，父进程只负责 deadline、进程树清理（Windows `taskkill /T /F`、POSIX 杀进程组）与退出码（0=成功/1=失败/124=超时），输出单行 `E2E_EVENT {json}` 事件（`phase=submitted|completed|failed|timeout`）；smoke 覆盖 `SH.000016`/`上证50`/`930955.CSI` 矩阵，期望 code/name 取脚本内置权威映射（不信任响应/结果自报身份，提交 code mismatch 输出含期望值与实际值的显式错误并携带结构化实际 `stock_code`，dispatcher 路由错误也失败），矩阵外 target 与非正 `--timeout` 在提交与 spawn 之前即被拒绝（退出码 2），completed 须 exact canonical code、exact 注册名称且 `analysis_summary`/`operation_advice`/`trend_prediction` 非空（仅空白视为空），失败或结果不完整即非零退出；超时清理进程树（Windows `taskkill /T /F`、POSIX 杀进程组），清理成功输出 `timeout` 事件并退出 124、清理失败输出含清理错误的 `failed` 事件并退出 1，不回滚 DB/报告/通知副作用；用户 Ctrl-C 中止时父进程同样先清理进程树，清理成功透传中断、清理失败输出含清理错误的 `failed` 事件并退出 1，绝不静默吞掉清理失败；worker 意外异常输出 `failed` 事件并退出 1（stderr 保留异常证据，`KeyboardInterrupt` 不按普通失败处理），父进程将 worker 任意其他退出码归一化为 1（运行时契约只暴露 0/1/124）；父进程以内部 `--worker` flag 显式拉起子进程（不依赖环境变量，防外部预置绕过硬超时）；不 mock 在线依赖、不 dry-run、不修 transport，不加入离线 gate。
- [新功能] Bot `/analyze` 支持已登记指数入口：显式代码（`sh000016`）、CSI alias（`930955.CSI` 收敛为 `csi930955`）与注册中文名（`上证50`）均可提交，指数以结构化 `AnalysisTarget` 经 `TaskService` 贯穿到 Pipeline `process_single_stock`（`sh000016` 不再被改写为 `SH000016`）；注册名称查询独立于 parser identity alias（中文名不进入 `find_by_explicit_key`/`parse_analysis_target`），同名歧义返回明确错误并要求显式代码，未登记 CSI 与未知名称返回明确错误且不提交任务；个股代码（A/HK/US）保持既有 legacy code 路径不变，股票名称输入（如 `贵州茅台`）由本次 Bot 入口新暴露——复用既有名称解析器（`resolve_name_to_code`）解析后提交 legacy code，不携带结构化 target；提交成功响应在 `BotResponse.extra` 暴露内部任务 identity（`task_id`/`stock_code`）供在线验收等内部流程使用，文本与错误路径不变、平台适配器可忽略 `extra`。
- [新功能] 新增最小 Agent 轨迹评估入口 `evals/agent_trajectory/`(Refs #1956):纯函数指标层只消费真实 `tool_calls_log + AgentResult`,冻结最小指标契约(工具命中、冗余/缓存、失败/重试、总步数/max_steps),`run_eval.py` 经 `build_agent_executor` 真实执行并输出文本摘要 + 结构化 JSON 报告;评估为 reporter 非 gate,零 `src/` 改动

- [修复] 将 litellm 依赖窗口上界收敛到 `<1.99.0`：1.99.0 起把 `prompt_cache_key` 透传给 OpenAI provider，破坏 provider 缓存测试对不透传行为的既有断言（CI backend-tests 3/3 与 backend-gate 失败）；保留历史最低版本与 `!=1.82.7`/`!=1.82.8` 事故排除，同时同步更新各 LLM 兼容文档中写死的依赖约束表述，避免文档与 requirements.txt 漂移

- [新功能] 新增 `SEARXNG_TIMEOUT_SECONDS` 配置自建 SearXNG 单次搜索超时（默认 10 秒），已接线全部 SearchService 构造入口（含题材搜索子进程重建）与默认 GitHub Actions 工作流

- [修复] 美股日线路由现按各数据源当前优先级排序，单项 `*_PRIORITY` 配置（如 `YFINANCE_PRIORITY=0`）对美股即时生效；指数固定首选与 Longbridge preferred 语义保持不变

- [新功能] 新增个股研究聚合 API，以统一 canonical code 返回行情、历史、研究产物、资讯、缓存持仓关系和监控规则，并对每个块独立标记 fresh/partial/unavailable。
- [修复] 个股研究聚合拒绝交易所冲突的股票身份，在市场限定后无历史候选时保持空结果，兼容市场限定裸码与混合大小写旧数据，并从独立基本面快照补齐 ResearchArtifact 的财报与分红证据。

- [新功能] 支持通过 `main.py --stocks` 一次性分析已登记板块指数，自动使用指数适用的数据与分析能力，并保持报告、历史和决策信号兼容。
- [修复] `main.py --stocks` 在解析股票列表前先 best-effort 刷新股票索引注册表，保证首次运行能吃到刷新后的指数 alias/身份；刷新失败、超时或禁用不阻断分析。
- [修复] 交易日过滤对市场未知的指数 code（如 `sh000016`/`csi930955`/`930955.CSI`）按 `market=cn` 参与 A 股休市过滤，避免休市日指数被 fail-open 保留；市场仍未知的非指数 code 继续保留。
- [修复] 指数分析将实际命中的日线数据源归因保存到历史记录，并由 Dashboard/Brief aggregate 报告展示；来源无效时保持原有输出。
- [文档] 在中英繁 README 顶部关联 DSA arXiv 论文，并新增 `CITATION.cff` 统一项目引用信息。
- [新功能] 新增数据源能力与数据集质量只读契约，提供 `/api/v1/data/overview` 和 `/api/v1/data/capabilities`，为大盘看板、数据中心、个股详情和自选 2.0 统一暴露 provider capability、dataset quality 和 source priority。
- [修复] 统一美股指数实时行情与数据能力概览为 YFinance-only 路由，避免 YFinance 失败后误用 Longbridge fallback。
- [改进] PR CI 增加文档路径检测：仅修改普通文档、非治理 Markdown 或 LICENSE 时跳过后端测试分片、Docker、Web 与桌面打包，保留轻量治理和门禁汇总；契约文档、静态 API 规格与测试 fixture 仍执行后端回归。
- [新功能] 新增 ResearchArtifact 结构化研究产物契约，在 `AnalysisReport.structured_report` 中承载 Thesis、Evidence、Invalidation Conditions、Next Actions 和 Data Quality，并提供从现有报告生成结构化产物的后端 helper 与 Web 类型。
- [修复] 同步 ResearchArtifact 与 `AnalysisReport.structured_report` 到静态 OpenAPI，避免公开 API 规格与运行时契约漂移。
- [修复] Linux/Docker 分享图补齐 Noto CJK 字体与中韩文字体栈，避免 PNG 只显示数字和英文、中文或韩文内容消失。
- [修复] 股票名称归一：AkShare 部分名称带无意义内嵌空格（“五 粮 液”、“万  科Ａ”）与全角宽度拼写（“京东方Ａ” 的全角 Ａ），统一经 `_normalize_stock_name()` 做 NFKC 宽度归一 + 去空白（原 `_compact_stock_name` 仅去空白）：本地映射初值、`_build_name_map_from_df()` 构建与 `extend_AkShare()` 合并、磁盘缓存加载三个入库口（含归一后为空的条目守卫）与 `resolver_name_to_code_list()` / `is_known_stock_name()` / `resolve_name_to_code()` 三个查询入口同源归一；消除空格/全角拼写与本地无空格半角拼写比较不相等造成的假性改名别名，源形态输入（带空格/全角）与常规拼写同样可解析，覆盖 `/analyze` API、按名称导入与 Bot 文本解析等全部调用路径；全角拼写此前与分词管道 NFKC 归一后的半角输入（“京东方A”）永不相等——全名精确匹配落空且会被更短库内名误切出错误实体（“京东”），归一后半角/全角输入产出一致、展示名统一为归一拼写；磁盘缓存中的历史未归一数据（带空格/全角）经合并与加载入口自动归一，无需迁移。
- [新功能] Web Chat 意图识别层新增分词模块：`web_intent_tokenizer` 六步管道（多股票全名实体扫描 → 标点/空白切分 → 代码形提取 → 市场关键词 → 无歧义关键词 → 残存 gap 多策略 DFS 匹配）把用户消息切分为携带语义标签的 Token 序列；配套 `web_intent_types` 数据字典（Token 结构、Market 枚举、21 个语义 tag、clean/extend 双词池与正则机器）。核心原则"宁可不做，不可做错"：Step 1~5 只做精确匹配，Step 6 要求整段 TAG 全覆盖（交叉验证）才产出，未覆盖片段保持空 tag 交下游 LLM 兜底；代码形 token 辨认为 `stock_code`（附 code/name/market 三元组）/ `wrong_{market}_code` / `unknown_{market}_code` 三态，token 层代码拼写统一 canonical 归一（a=6 位裸数字、hk=HK+5 位、us=大写 ticker）。意图枚举与意图识别结果随后续 `web_intent_resolver` PR 引入。新增 183 个分词单元测试。
- [新功能] 完善 Futu OpenD 港股数据源接入：系统设置支持 OpenD 地址、端口和港股实时数据源优先级，保留 Longbridge、AkShare、YFinance fallback。
- [测试] 增加 Futu 配置 schema、港股实时路由和 fallback 契约覆盖。

- [新功能] 建立唯一、可生成、可校验、可降级的指数身份注册表：由 `scripts/stock_index_seeds/index_registry.csv` 的 31 项 manifest 确定性合并进 `apps/dsa-web/public/stocks.index.json`，运行时唯一真源为 JSON 中通过校验的 `active=true`/`assetType=index` 行，移除 `stock_list_parser` 的 5 项硬编码白名单；支持 `--index-only` 生成与字节稳定输出。
- [新功能] 补齐显式 SH/SZ/CSI 指数 alias 收敛与 CSI 身份：`sh000300`/`000300.SH`/`sz399300`/`399300.SZ`/`000300.CSI` 均解析到 `sh000300`，`csi930955`/`930955.CSI` 解析到 `csi930955`；未登记 `.CSI` 输入返回 `unsupported`；裸数字恒为 stock 并仅通过 `matched_index` 暴露歧义。
- [新功能] 数据管理器按 SH/SZ/CSI 支持矩阵映射 provider symbol：CSI 仅 AkShare 支持（`csi{code}`），Tencent/TickFlow/Yahoo 返回空 symbol 并记录 `unsupported` provider-run，不触发指数健康熔断。
- [改进] 存储层 `_derive_canonical_id` 统一为 parser 推导（裸码=stock、显式指数=index），并新增幂等分批修复历史裸码错误 canonical 串桶（`000001`/`000016`/`000688`/`930955` 等），显式指数行与正确 stock 行不受影响，registry 为空时修复 no-op。
- [改进] Web loader 完整解压含 index 的共享 payload，但在返回给 autocomplete/popular/group 消费面前过滤 `assetType=index`，股票与 ETF 行为保持不变。
- [测试] 为生成器、loader、parser、provider 路由、存储修复与 Web 门槛补充 TDD 回归锚点。
- [修复] PR #2267 review 收敛 CSI 显式身份：将 `csi` prefix（canonical）与 `.CSI` suffix（显式 alias）在 parser/build/runtime 规范化器中分离，未登记显式 `csiNNNNNN`/`NNNNNN.CSI` 一律返回 `unsupported`（不再落入美股或猜测 SH/SZ），并防止未登记 `csi000300` 被等价成已登记 `000300.CSI` alias；存储 `_derive_canonical_id` 对 unsupported 输入返回 NULL，避免进入持久化 canonical 桶。
- [修复] 在 seed、build entry 与 runtime candidate 三层严格校验 alias 唯一性与整数 popularity：NFKC/casefold 等价 alias 跨条目冲突被拒绝（无静默覆盖），非负整数之外（小数/布尔/负值/字符串）popularity 一律拒绝，整数 `100` 保持有效。
- [修复] 收敛已登记 CSI 显式身份在 resolver、任务去重键与历史候选中的分裂：`csi930955`/`930955.CSI`/`CSI930955` 统一解析为 parser canonical `csi930955`，未登记 `csi930956`/`930956.CSI` 保持既有降级语义；`is_code_like()`、REST/watchlist 输入边界与完整 Pipeline 透传不变。
- [修复] 阻止任意更新的非 bundled 指数候选（含 legacy `static` 子集）在 remote 缺失/损坏时以 active-index 子集覆盖 bundled baseline：所有非 bundled 候选必须为 bundled active-index canonical 集合的合法超集，否则回退 bundled 并记录 WARNING。
- [新功能] 桌面端全局右上角增加更新入口，与设置页共用更新状态；普通浏览器 WebUI 不展示，且不会在挂载时重复触发后台检查。
- [修复] 桌面端右上角更新入口与设置页共用检查中状态，避免一侧检查时另一侧仍可重复触发 GitHub Releases 检查；主进程手动检查路径同步增加 in-flight 防重。
- [新功能] Web 自动补全与搜索放行已登记指数（注册中文名/`sh`/`sz` 前缀/`csi`/`.CSI` 显式形式均可检索与提交），热门候选仍仅股票；`/analyze` API 对显式指数输入构造结构化 `AnalysisTarget`（INDEX 用 `canonical_id` 去重，与同码个股互不折叠，CSI alias 收敛），未登记 CSI 单请求返回明确 4xx、异步批量仅该目标进入响应 `rejected` 列表；指数 target 经任务队列贯穿到 Pipeline `process_single_stock`，`DecisionSignal` 以 `market_override="cn"` 落库并有真实分支测试。
- [修复] `/analyze` 在解析前按 strip 后非空原始 token 数限制 50 上限，rejected/duplicate token 也计入，防止用拒绝或重复 token 绕过批量上限；以唯一 `is_single = len(stock_codes) == 1 and not rejected_entries` 统一驱动 metadata、409 与单任务 202，duplicate+rejected 混合批次不再误返 legacy 409（单 duplicate 仍 409、部分 rejected 仍 202、全 rejected 仍 400）。
- [新功能] 报告 meta 补充可选 `asset_type`（`stock`/`index`），由后端 canonical code 经 `parse_analysis_target` 生成权威类型；指数报告在 Web 报告页与 Chat 自选入口隐藏 stock-only 自选操作，裸同码股票（如 `000016`）保持股票行为，market review 与旧客户端可缺省。
- [修复] Web 批量分析把 accepted/duplicates/rejected 三类计入确认数，含 rejected 的完整 chunk 继续提交下一 chunk 而非误报 incomplete，最终以 warning 展示拒绝数量与首个拒绝原因（中英文文案）。
- [修复] 历史筛选/删除/计数与 stock-bar 对已登记指数按 parser canonical 身份隔离：`sh000016`/`SH000016`/`000016.SH` 等显式形态互相可达（lowercase canonical + uppercase legacy canonical + 显式 alias），但永远不命中同码裸股票，裸码查询也不会命中指数记录；同一指数多条显式形态旧记录在 `/history/stocks` 合并为一行并计数全部形态，无记录删除仍返回 `deleted=0`。SH/SZ/CSI 共用同一 parser 分支，股票 alias、港股与海外市场行为不变。历史列表、历史详情与 stock-bar 对已登记指数（含旧 uppercase/显式 alias 持久化记录，如 `SZ399300`、`000300.CSI`）的 API `stock_code` 一律输出 parser canonical（`sh000300`/`csi930955`）。
- [改进] 任务列表/SSE 事件、历史列表项与 stock-bar 项追加可选 `asset_type`（`stock`/`index`）：任务侧从已提交的 `analysis_target` 透传（不重新猜测），历史与 stock-bar 侧由持久化 `record.code` 经 `parse_analysis_target` 生成；旧客户端与 market review 可缺省，字段可选追加不破坏既有契约。
- [修复] Web 首页与自选工作区改用资产感知身份键：任务/报告/历史的 `assetType` 优先，且被后端保证为 parser canonical 的代码只做**大小写折叠**（`SH000016`→`sh000016`），禁止再用前缀/后缀正则猜 canonical（否则 `000300.CSI` 会被误猜成 `csi000300`、`sz399300` 被误当成独立 canonical，违反注册表唯一判型真源）；仅 watchlist 原始字符串缺少类型时，才用已加载 `stocks.index.json` 的 `assetType=index` 行 canonical/display/显式 alias 精确命中（不先 normalize、不用前缀正则猜测；加载期间禁用批量分析，加载失败或请求超过 10 秒时按既有股票语义 fail-open）；行选中、active task 与完成自动选中按资产类型分桶，`sh000016` 指数行与 `000016` 股票行状态独立，完成后自动选中正确 canonical 指数报告。
- [修复] Chat 消息恢复、发送与报告追问对显式 SH/SZ/CSI 已登记指数统一按注册表 canonical 判型并覆盖默认 LiteLLM 与 Codex：所有 Chat 后端首帧加载 registry，加载期间延迟 URL/历史恢复并禁用发送，settle 后 `sh000016`/`sz399001`/`000016.SH`/`930955.CSI`/`csi930955` 只产出一个 lowercase canonical；后端 `resolve_stock_scope`、工具守卫与 cache key 复用 parser `INDEX` 身份，保持指数与裸同码股票隔离；未登记、空 registry 或加载失败时维持既有股票 fail-open，绝不按前缀猜指数。
- [修复] 选股结果持久化恢复：选股页新增历史记录区块，任务完成后保留 run_id，刷新页面可从历史 API 恢复上次选股结果（此前刷新后结果丢失）。
- [修复] Web/API runtime scheduler 使用跨平台独立进程执行分析，并在默认 45 分钟硬超时或服务停止后清理进程树；停止返回后不再派发新的自动任务，避免一次卡死阻断后续调度。
- [改进] Tavily 搜索深度由 `advanced` 调整为 `basic`，降低搜索 credit 消耗（#2314）。
- [修复] Web 的 axios 依赖升级至 `^1.18.0`，桌面端通过 override 固定 js-yaml 为 `4.3.1`，纳入依赖安全更新（#2256、#2254）。

## [3.31.0] - 2026-08-23

### 发布亮点

- feat: Agent 工具调用新增按类别和单工具配置的超时契约，并补齐防重试、协作取消、并发预算与热重载一致性。
- feat: 股票名称解析、`canonical_id` 双写和 A 股指数多数据源路由共同完善股票身份与行情降级链路。
- improve: 新闻检索为空时在报告中如实披露证据边界，Anspire 默认覆盖全球区域，公共 SearXNG 实例改为显式启用。
- fix: 定时任务恢复、无报告失败反馈、通知发送和大盘复盘历史/诊断信息进一步收敛，减少静默失败与误导展示。
- security: 桌面端升级 `builder-util-runtime`，修复 CVE-2026-54673 涉及的重定向凭据头信息泄露风险。
- docs: 增加 xAI Grok 的 LiteLLM 配置示例、Grok Bot 集成说明与可复用 Skill。

### 变更明细

- [修复] 大盘复盘历史列表与详情统一展示持久化短摘要；旧记录缺少摘要时从完整 Markdown 生成无内部标记的纯文本节选。
- [修复] 大盘复盘按实际执行的生成后端和模型记录诊断，避免 Codex CLI 或 fallback 被误显示为配置模型。
- [修复] 已配置钉钉 Webhook 时不再误报“未配置通知渠道”；钉钉 Stream 仍仅用于交互，不作为定时静态推送渠道。
- [修复] WebUI/API/Desktop 以 `--serve-only` 重启后会恢复已启用的定时任务，同时保持启动时不立即执行分析；通知路由示例补充钉钉 Webhook 渠道。
- [改进] AIHubMix 注册与引流链接统一使用 inferera.com，改善中国大陆网络直连体验。
- [修复] 单股推送模式在未配置通知渠道时仍会落盘本地个股报告；CLI 启动分析若因空股票列表、个股结果全失败或本地报告保存失败而未生成报告，会显式返回失败并记录原因。
- [修复] 合并推送模式下即使个股汇总报告落盘失败，仍会先发送已有的合并通知；仅启用大盘复盘但最终未生成任何复盘内容时，分析任务会显式返回失败。
- [修复] SearXNG 公共实例发现的默认值由启用改为关闭：公共实例普遍存在限流、下线或不返回 JSON 的情况，默认开启会让未配置搜索 key 的用户每次分析多耗 30~60 秒且新闻面最终为空。运行时默认值、配置模板、中英文档与工作流诊断同步调整；显式设为 true 的用户行为不变。
- [改进] 新闻检索未执行或零命中时，报告中如实标注结论未纳入新闻面证据：零命中与「未配置搜索渠道」使用各自独立的文案，覆盖日报 / dashboard / brief / 个股 / 企业微信与模板渲染的详细与摘要分支、历史报告与分享导出、报告详情 API 与 Web 报告详情页，并按 `zh` / `en` / `ko` 分别本地化。此前该情况下消息面章节直接消失，读者无从区分「确实没有新闻」与「检索静默失败」。披露以本次分析实际收到的消息面证据为准，涵盖实时检索、社交情绪与本地已落库的资讯池三路来源；搜索命中数仅用于在确无证据时说明原因（未配置渠道 / 检索零命中），避免把已用到本地或社交证据的分析误报成「未纳入新闻面证据」。Agent 模式的命中数取自 Agent 实际消费的搜索工具结果，而非分析结束后为持久化情报而补打的查询。

- [新功能] Agent 工具调用支持按类别（data/search/analysis/action/market）配置默认超时，并允许单工具声明 `timeout_seconds`；有效超时按 first-wins 优先级解析（显式 per-run `tool_call_timeout_seconds` > 单工具显式 `timeout_seconds` > 类别默认 > 无限制），剩余 wall-clock 预算仅作不可突破的外层 cap，超时后返回结构化 `{"timeout": true}` 错误（标记 `retriable: false` 并写入 `non_retriable_tool_results` 防重试重复执行）供 Agent 继续执行而非中断循环（fixes #1890）。
- [修复] Agent 工具注册表（`src/agent/factory.get_tool_registry`）由模块级缓存改为按「类别超时映射的值」比对失效，规避 CPython 回收对象后地址复用（`id(config)` 相同）导致配置 reload 后的 `Config` 被误判为未变、沿用过期超时的真 bug；新增 `_coerce_config_timeout` 类型白名单，使调用方传入 `MagicMock` / 缺属性 stub / 脏字符串（如 `float(MagicMock())` 静默得到 1.0）时降级为「无类别限制」而非崩溃或强加 1 秒超时；`build_agent_executor(config)` / `build_agent_chat_executor(config)` 现已把调用方 `config` 透传给 `get_tool_registry(config)`（不再无参调用冻结首构 registry）；`main._reload_runtime_config` 与 `SystemConfigService._reload_runtime_singletons`（及 `update()`→`reload_now` 路径）在配置热重载时调用 `reset_tool_registry()` 强制重建；回归测试补充「传入新 config 后 registry 重建」「reload 后新超时应生效」及「builder 透传 config」三类场景（#1890 的 review follow-up，闭环 OR-COM-dd1e8fa7 / OR-COM-bff42110）
- [修复] Agent 工具超时 review 闭环（fixes #1890 的 4 个 blocker）：超时解析由 min 契约改为 first-wins（显式 per-run `tool_call_timeout_seconds` > 单工具 `ToolDefinition.timeout_seconds` > 类别默认 > 无限制，剩余 wall-clock 预算只作不可突破的外层 cap；research 路径不再传 `tool_call_timeout_seconds` 以免覆盖类别限制）；超时结果标记 `retriable: false` 并写入 `non_retriable_tool_results` 阻断 LLM 同调用重试重入，且…47094 tokens truncated…个定时点

### 修复
- 🐛 修复 Web UI 页面居中问题
- 🐛 修复 Settings 返回 500 错误

## [3.2.9] - 2026-02-22

### 修复
- 🐛 **ETF 分析仅关注指数走势**（Issue #274）
  - 美股/港股 ETF（如 VOO、QQQ）与 A 股 ETF 不再纳入基金公司层面风险（诉讼、声誉等）
  - 搜索维度：ETF/指数专用 risk_check、earnings、industry 查询，避免命中基金管理人新闻
  - AI 提示：指数型标的分析约束，`risk_alerts` 不得出现基金管理人公司经营风险

## [3.2.8] - 2026-02-21

### 修复
- 🐛 **BOT 与 WEB UI 股票代码大小写统一**（Issue #355）
  - BOT `/analyze` 与 WEB UI 触发分析的股票代码统一为大写（如 `aapl` → `AAPL`）
  - 新增 `canonical_stock_code()`，在 BOT、API、Config、CLI、task_queue 入口处规范化
  - 历史记录与任务去重逻辑可正确识别同一股票（大小写不再影响）

## [3.2.7] - 2026-02-20

### 新增
- 🔐 **Web 页面密码验证**（Issue #320, #349）
  - 支持 `ADMIN_AUTH_ENABLED=true` 启用 Web 登录保护
  - 首次访问在网页设置初始密码；支持「系统设置 > 修改密码」和 CLI `python -m src.auth reset_password` 重置

## [3.2.6] - 2026-02-20
### ⚠️ 破坏性变更（Breaking Changes）

- **历史记录 API 变更 (Issue #322)**
  - 路由变更：`GET /api/v1/history/{query_id}` → `GET /api/v1/history/{record_id}`
  - 参数变更：`query_id` (字符串) → `record_id` (整数)
  - 新闻接口变更：`GET /api/v1/history/{query_id}/news` → `GET /api/v1/history/{record_id}/news`
  - 原因：`query_id` 在批量分析时可能重复，无法唯一标识单条历史记录。改用数据库主键 `id` 确保唯一性
  - 影响范围：使用旧版历史详情 API 的所有客户端需同步更新

### 修复
- 修复美股（如 ADBE）技术指标矛盾：akshare 美股复权数据异常，统一美股历史数据源为 YFinance（Issue #311）
- 🐛 **历史记录查询和显示问题 (Issue #322)**
  - 修复历史记录列表查询中日期不一致问题：使用明天作为 endDate，确保包含今天全天的数据
  - 修复服务器 UI 报告选择问题：原因是多条记录共享同一 `query_id`，导致总是显示第一条。现改用 `analysis_history.id` 作为唯一标识
  - 历史详情、新闻接口及前端组件已全面适配 `record_id`
  - 新增后台轮询（每 30s）与页面可见性变更时静默刷新历史列表，确保 CLI 发起的分析完成后前端能及时同步，使用 `silent` 模式避免触发 loading 状态
- 🐛 **美股指数实时行情与日线数据** (Issue #273)
  - 修复 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指数无法获取实时行情的问题
  - 新增 `us_index_mapping` 模块，将用户输入（如 SPX）映射为 Yahoo Finance 符号（如 ^GSPC）
  - 美股指数与美股股票日线数据直接路由至 YfinanceFetcher，避免遍历不支持的数据源
  - 消除重复的美股识别逻辑，统一使用 `is_us_stock_code()` 函数

### 优化
- 🎨 **首页输入栏与 Market Sentiment 布局对齐优化**
  - 股票代码输入框左缘与历史记录 glass-card 框左对齐
  - 分析按钮右缘与 Market Sentiment 外框右对齐
  - Market Sentiment 卡片向下拉伸填满格子，消除与 STRATEGY POINTS 之间的空隙
  - 窄屏时输入栏填满宽度，响应式对齐保持一致

## [3.2.5] - 2026-02-19

### 新增
- 🌍 **大盘复盘可选区域**（Issue #299）
  - 支持 `MARKET_REVIEW_REGION` 环境变量：`cn`（A股）、`us`（美股）、`both`（两者）
  - us 模式使用 SPX/纳斯达克/道指/VIX 等指数；both 模式可同时复盘 A 股与美股
  - 默认 `cn`，保持向后兼容

## [3.2.4] - 2026-02-18

### 修复
- 🐛 **统一美股数据源为 YFinance**（Issue #311）
  - akshare 美股复权数据异常，统一美股历史数据源为 YFinance
  - 修复 ADBE 等美股股票技术指标矛盾问题

## [3.2.3] - 2026-02-18

### 修复
- 🐛 **标普500实时数据缺失**（Issue #273）
  - 修复 SPX、DJI、IXIC、NDX、VIX、RUT 等美股指数无法获取实时行情的问题
  - 新增 `us_index_mapping` 模块，将用户输入（如 SPX）映射为 Yahoo Finance 符号（如 `^GSPC`）
  - 美股指数与美股股票日线数据直接路由至 YfinanceFetcher，避免遍历不支持的数据源

## [3.2.2] - 2026-02-16

### 新增
- 📊 **PE 指标支持**（Issue #296）
  - AI System Prompt 增加 PE 估值关注
- 📰 **新闻时效性筛查**（Issue #296）
  - `NEWS_MAX_AGE_DAYS`：新闻最大时效（天），默认 3，避免使用过时信息
- 📈 **强势趋势股乖离率放宽**（Issue #296）
  - `BIAS_THRESHOLD`：乖离率阈值（%），默认 5.0，可配置
  - 强势趋势股（多头排列且趋势强度 ≥70）自动放宽乖离率到 1.5 倍

## [3.2.1] - 2026-02-16

### 新增
- 🔧 **东财接口补丁可配置开关**
  - 支持 `EFINANCE_PATCH_ENABLED` 环境变量开关东财接口补丁（默认 `true`）
  - 补丁不可用时可降级关闭，避免影响主流程

## [3.2.0] - 2026-02-15

### 新增
- 🔒 **CI 门禁统一（P0）**
  - 新增 `scripts/ci_gate.sh` 作为后端门禁单一入口
  - 主 CI 改为 `backend-gate`、`docker-build`、`web-gate` 三段式
  - CI 触发改为所有 PR，避免 Required Checks 因路径过滤缺失而卡住合并
  - `web-gate` 支持前端路径变更按需触发
  - 新增 `network-smoke` 工作流承载非阻断网络场景回归
- 📦 **发布链路收敛（P0）**
  - `docker-publish` 调整为 tag 主触发，并增加发布前门禁校验
  - 手动发布增加 `release_tag` 输入与 semver/changelog 强校验
  - 发布前新增 Docker smoke（关键模块导入）
- 📝 **PR 模板升级（P0）**
  - 增加背景、范围、验证命令与结果、回滚方案、Issue 关联等必填项
- 🤖 **AI 审查覆盖增强（P0）**
  - `pr-review` 纳入 `.github/workflows/**` 范围
  - 新增 `AI_REVIEW_STRICT` 开关，可选将 AI 审查失败升级为阻断

## [3.1.13] - 2026-02-15

### 新增
- 📊 **仅分析结果摘要**（Issue #262）
  - 支持 `REPORT_SUMMARY_ONLY` 环境变量，设为 `true` 时只推送汇总，不含个股详情
  - 默认 `false`，多股时适合快速浏览

## [3.1.12] - 2026-02-15

### 新增
- 📧 **个股与大盘复盘合并推送**（Issue #190）
  - 支持 `MERGE_EMAIL_NOTIFICATION` 环境变量，设为 `true` 时将个股分析与大盘复盘合并为一次推送
  - 默认 `false`，减少邮件数量、降低被识别为垃圾邮件的风险

## [3.1.11] - 2026-02-15

### 新增
- 🤖 **Anthropic Claude API 支持**（Issue #257）
  - 支持 `ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`、`ANTHROPIC_TEMPERATURE`、`ANTHROPIC_MAX_TOKENS`
  - AI 分析优先级：Gemini > Anthropic > OpenAI
- 📷 **从图片识别股票代码**（Issue #257）
  - 上传自选股截图，通过 Vision LLM 自动提取股票代码
  - API: `POST /api/v1/stocks/extract-from-image`；支持 JPEG/PNG/WebP/GIF，最大 5MB
  - 支持 `OPENAI_VISION_MODEL` 单独配置图片识别模型
- ⚙️ **通达信数据源手动配置**（Issue #257）
  - 支持 `PYTDX_HOST`、`PYTDX_PORT` 或 `PYTDX_SERVERS` 配置自建通达信服务器

## [3.1.10] - 2026-02-15

### 新增
- ⚙️ **立即运行配置**（Issue #332）
  - 支持 `RUN_IMMEDIATELY` 环境变量，`true` 时定时任务启动后立即执行一次
- 🐛 修复 Docker 构建问题

## [3.1.9] - 2026-02-14

### 新增
- 🔌 **东财接口补丁机制**
  - 新增 `patch/eastmoney_patch.py` 修复 efinance 上游接口变更
  - 不影响其他数据源的正常运行

## [3.1.8] - 2026-02-14

### 新增
- 🔐 **Webhook 证书校验开关**（Issue #265）
  - 支持 `WEBHOOK_VERIFY_SSL` 环境变量，可关闭 HTTPS 证书校验以支持自签名证书
  - 默认保持校验，关闭存在 MITM 风险，仅建议在可信内网使用

## [3.1.7] - 2026-02-14

### 修复
- 🐛 修复包导入错误（package import error）

## [3.1.6] - 2026-02-13

### 修复
- 🐛 修复 `news_intel` 中 `query_id` 不一致问题

## [3.1.5] - 2026-02-13

### 新增
- 📷 **Markdown 转图片通知**（Issue #289）
  - 支持 `MARKDOWN_TO_IMAGE_CHANNELS` 配置，对 Telegram、企业微信、自定义 Webhook（Discord）、邮件发送图片格式报告
  - 邮件为内联附件，增强对不支持 HTML 客户端的兼容性
  - 需安装 `wkhtmltopdf` 和 `imgkit`

## [3.1.4] - 2026-02-12

### 新增
- 📧 **股票分组发往不同邮箱**（Issue #268）
  - 支持 `STOCK_GROUP_N` + `EMAIL_GROUP_N` 配置，不同股票组报告发送到对应邮箱
  - 大盘复盘发往所有配置的邮箱

## [3.1.3] - 2026-02-12

### 修复
- 🐛 修复 Docker 内运行时通过页面修改配置报错 `[Errno 16] Device or resource busy` 的问题

## [3.1.2] - 2026-02-11

### 修复
- 🐛 修复 Docker 一致性问题，解决关键批次处理与通知 Bug

## [3.1.1] - 2026-02-11

### 变更
- ♻️ `API_HOST` → `WEBUI_HOST`：Docker Compose 配置项统一

## [3.1.0] - 2026-02-11

### 新增
- 📊 **ETF 支持增强与代码规范化**
  - 统一各数据源 ETF 代码处理逻辑
  - 新增 `canonical_stock_code()` 统一代码格式，确保数据源路由正确

## [3.0.5] - 2026-02-08

### 修复
- 🐛 修复信号 emoji 与建议不一致的问题（复合建议如"卖出/观望"未正确映射）
- 🐛 修复 `*ST` 股票名在微信/Dashboard 中 markdown 转义问题
- 🐛 修复 `idx.amount` 为 None 时大盘复盘 TypeError
- 🐛 修复分析 API 返回 `report=None` 及 ReportStrategy 类型不一致问题
- 🐛 修复 Tushare 返回类型错误（dict → UnifiedRealtimeQuote）及 API 端点指向

### 新增
- 📊 大盘复盘报告注入结构化数据（涨跌统计、指数表格、板块排名）
- 🔍 搜索结果 TTL 缓存（500 条上限，FIFO 淘汰）
- 🔧 Tushare Token 存在时自动注入实时行情优先级
- 📰 新闻摘要截断长度 50→200 字

### 优化
- ⚡ 补充行情字段请求限制为最多 1 次，减少无效请求

## [3.0.4] - 2026-02-07

### 新增
- 📈 **回测引擎** (PR #269)
  - 新增基于历史分析记录的回测系统，支持收益率、胜率、最大回撤等指标评估
  - WebUI 集成回测结果展示

## [3.0.3] - 2026-02-07

### 修复
- 🐛 修复狙击点位数据解析错误问题 (PR #271)

## [3.0.2] - 2026-02-06

### 新增
- ✉️ 可配置邮件发送者名称 (PR #272)
- 🌐 外国股票支持英文关键词搜索

## [3.0.1] - 2026-02-06

### 修复
- 🐛 修复 ETF 实时行情获取、市场数据回退、企业微信消息分块问题
- 🔧 CI 流程简化

## [3.0.0] - 2026-02-06

### 移除
- 🗑️ **移除旧版 WebUI**
  - 删除基于 `http.server.ThreadingHTTPServer` 的旧版 WebUI（`web/` 包）
  - 旧版 WebUI 的功能已完全被 FastAPI（`api/`）+ React 前端替代
  - `--webui` / `--webui-only` 命令行参数标记为弃用，自动重定向到 `--serve` / `--serve-only`
  - `WEBUI_ENABLED` / `WEBUI_HOST` / `WEBUI_PORT` 环境变量保持兼容，自动转发到 FastAPI 服务
  - `webui.py` 保留为兼容入口，启动时直接调用 FastAPI 后端
  - Docker Compose 中移除 `webui` 服务定义，统一使用 `server` 服务

### 变更
- ♻️ **服务层重构**
  - 将 `web/services.py` 中的异步任务服务迁移至 `src/services/task_service.py`
  - Bot 分析命令（`bot/commands/analyze.py`）改为使用 `src.services.task_service`
  - Docker 环境变量 `WEBUI_HOST`/`WEBUI_PORT` 更名为 `API_HOST`/`API_PORT`（旧名仍兼容）

## [2.3.0] - 2026-02-01

### 新增
- 🇺🇸 **增强美股支持** (Issue #153)
  - 实现基于 Akshare 的美股历史数据获取 (`ak.stock_us_daily()`)
  - 实现基于 Yfinance 的美股实时行情获取（优先策略）
  - 增加对不支持数据源（Tushare/Baostock/Pytdx/Efinance）的美股代码过滤和快速降级

### 修复
- 🐛 修复 AMD 等美股代码被误识别为 A 股的问题 (Issue #153)

## [2.2.5] - 2026-02-01

### 新增
- 🤖 **AstrBot 消息推送** (PR #217)
  - 新增 AstrBot 通知渠道，支持推送到 QQ 和微信
  - 支持 HMAC SHA256 签名验证，确保通信安全
  - 通过 `ASTRBOT_URL` 和 `ASTRBOT_TOKEN` 配置

## [2.2.4] - 2026-02-01

### 新增
- ⚙️ **可配置数据源优先级** (PR #215)
  - 支持通过环境变量（如 `YFINANCE_PRIORITY=0`）动态调整数据源优先级
  - 无需修改代码即可优先使用特定数据源（如 Yahoo Finance）

## [2.2.3] - 2026-01-31

### 修复
- 📦 更新 requirements.txt，增加 `lxml_html_clean` 依赖以解决兼容性问题

## [2.2.2] - 2026-01-31

### 修复
- 🐛 修复代理配置区分大小写问题 (fixes #211)

## [2.2.1] - 2026-01-31

### 修复
- 🐛 **YFinance 兼容性修复** (PR #210, fixes #209)
  - 修复新版 yfinance 返回 MultiIndex 列名导致的数据解析错误

## [2.2.0] - 2026-01-31

### 新增
- 🔄 **多源回退策略增强**
  - 实现了更健壮的数据获取回退机制 (feat: multi-source fallback strategy)
  - 优化了数据源故障时的自动切换逻辑

### 修复
- 🐛 修复 analyzer 运行后无法通过改 .env 文件的 stock_list 内容调整跟踪的股票

## [2.1.14] - 2026-01-31

### 文档
- 📝 更新 README 和优化 auto-tag 规则

## [2.1.13] - 2026-01-31

### 修复
- 🐛 **Tushare 优先级与实时行情** (Fixed #185)
  - 修复 Tushare 数据源优先级设置问题
  - 修复 Tushare 实时行情获取功能

## [2.1.12] - 2026-01-30

### 修复
- 🌐 修复代理配置在某些情况下的区分大小写问题
- 🌐 修复本地环境禁用代理的逻辑

## [2.1.11] - 2026-01-30

### 优化
- 🚀 **飞书消息流优化** (PR #192)
  - 优化飞书 Stream 模式的消息类型处理
  - 修改 Stream 消息模式默认为关闭，防止配置错误运行时报错

## [2.1.10] - 2026-01-30

### 合并
- 📦 合并 PR #154 贡献

## [2.1.9] - 2026-01-30

### 新增
- 💬 **微信文本消息支持** (PR #137)
  - 新增微信推送的纯文本消息类型支持
  - 添加 `WECHAT_MSG_TYPE` 配置项

## [2.1.8] - 2026-01-30

### 修复
- 🐛 修正日志中 API 提供商显示错误 (PR #197)

## [2.1.7] - 2026-01-30

### 修复
- 🌐 禁用本地环境的代理设置，避免网络连接问题

## [2.1.6] - 2026-01-29

### 新增
- 📡 **Pytdx 数据源 (Priority 2)**
  - 新增通达信数据源，免费无需注册
  - 多服务器自动切换
  - 支持实时行情和历史数据
- 🏷️ **多源股票名称解析**
  - DataFetcherManager 新增 `get_stock_name()` 方法
  - 新增 `batch_get_stock_names()` 批量查询
  - 自动在多数据源间回退
  - Tushare 和 Baostock 新增股票名称/列表方法
- 🔍 **增强搜索回退**
  - 新增 `search_stock_price_fallback()` 用于数据源全部失败时
  - 新增搜索维度：市场分析、行业分析
  - 最大搜索次数从 3 增加到 5
  - 改进搜索结果格式（每维度 4 条结果）

### 改进
- 更新搜索查询模板以提高相关性
- 增强 `format_intel_report()` 输出结构

## [2.1.5] - 2026-01-29

### 新增
- 📡 新增 Pytdx 数据源和多源股票名称解析功能

## [2.1.4] - 2026-01-29

### 文档
- 📝 更新赞助商信息

## [2.1.3] - 2026-01-28

### 文档
- 📝 重构 README 布局
- 🌐 新增繁体中文翻译 (README_CHT.md)

### 修复
- 🐛 修复 WebUI 无法输入美股代码问题
  - 输入框逻辑改成所有字母都转换成大写
  - 支持 `.` 的输入（如 `BRK.B`）

## [2.1.2] - 2026-01-27

### 修复
- 🐛 修复个股分析推送失败和报告路径问题 (fixes #166)
- 🐛 修改 CR 错误，确保微信消息最大字节配置生效

## [2.1.1] - 2026-01-26

### 新增
- 🔧 添加 GitHub Actions auto-tag 工作流
- 📡 添加 yfinance 兜底数据源及数据缺失警告

### 修复
- 🐳 修复 docker-compose 路径和文档命令
- 🐳 Dockerfile 补充 copy src 文件夹 (fixes #145)

## [2.1.0] - 2026-01-25

### 新增
- 🇺🇸 **美股分析支持**
  - 支持美股代码直接输入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作为美股数据源
- 📈 **MACD 和 RSI 技术指标**
  - MACD：趋势确认、金叉死叉信号（零轴上金叉⭐、金叉✅、死叉❌）
  - RSI：超买超卖判断（超卖⭐、强势✅、超买⚠️）
  - 指标信号纳入综合评分系统
- 🎮 **Discord 推送支持** (PR #124, #125, #144)
  - 支持 Discord Webhook 和 Bot API 两种方式
  - 通过 `DISCORD_WEBHOOK_URL` 或 `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` 配置
- 🤖 **机器人命令交互**
  - 钉钉机器人支持 `/分析 股票代码` 命令触发分析
  - 支持 Stream 长连接模式
- 🌡️ **AI 温度参数可配置** (PR #142)
  - 支持自定义 AI 模型温度参数
- 🐳 **Zeabur 部署支持**
  - 添加 Zeabur 镜像部署工作流
  - 支持 commit hash 和 latest 双标签

### 重构
- 🏗️ **项目结构优化**
  - 核心代码移至 `src/` 目录，根目录更清爽
  - 文档移至 `docs/` 目录
  - Docker 配置移至 `docker/` 目录
  - 修复所有 import 路径，保持向后兼容
- 🔄 **数据源架构升级**
  - 新增数据源熔断机制，单数据源连续失败自动切换
  - 实时行情缓存优化，批量预取减少 API 调用
  - 网络代理智能分流，国内接口自动直连
- 🤖 Discord 机器人重构为平台适配器架构

### 修复
- 🌐 **网络稳定性增强**
  - 自动检测代理配置，对国内行情接口强制直连
  - 修复 EfinanceFetcher 偶发的 `ProtocolError`
  - 增加对底层网络错误的捕获和重试机制
- 📧 **邮件渲染优化**
  - 修复邮件中表格不渲染问题 (#134)
  - 优化邮件排版，更紧凑美观
- 📢 **企业微信推送修复**
  - 修复大盘复盘推送不完整问题
  - 增强消息分割逻辑，支持更多标题格式
  - 增加分批发送间隔，避免限流丢失
- 👷 **CI/CD 修复**
  - 修复 GitHub Actions 中路径引用的错误

## [2.0.0] - 2026-01-24

### 新增
- 🇺🇸 **美股分析支持**
  - 支持美股代码直接输入（如 `AAPL`, `TSLA`）
  - 使用 YFinance 作为美股数据源
- 🤖 **机器人命令交互** (PR #113)
  - 钉钉机器人支持 `/分析 股票代码` 命令触发分析
  - 支持 Stream 长连接模式
  - 支持选择精简报告或完整报告
- 🎮 **Discord 推送支持** (PR #124)
  - 支持 Discord Webhook 推送
  - 添加 Discord 环境变量到工作流

### 修复
- 🐳 修复 WebUI 在 Docker 中绑定 0.0.0.0 (fixed #118)
- 🔔 修复飞书长连接通知问题
- 🐛 修复 `analysis_delay` 未定义错误
- 🔧 启动时 config.py 检测通知渠道，修复已配置自定义渠道情况下仍然提示未配置问题

### 改进
- 🔧 优化 Tushare 优先级判断逻辑，提升封装性
- 🔧 修复 Tushare 优先级提升后仍排在 Efinance 之后的问题
- ⚙️ 配置 TUSHARE_TOKEN 时自动提升 Tushare 数据源优先级
- ⚙️ 实现 4 个用户反馈 issue (#112, #128, #38, #119)

## [1.6.0] - 2026-01-19

### 新增
- 🖥️ WebUI 管理界面及 API 支持（PR #72）
  - 全新 Web 架构：分层设计（Server/Router/Handler/Service）
  - 核心 API：支持 `/analysis` (触发分析), `/tasks` (查询进度), `/health` (健康检查)
  - 交互界面：支持页面直接输入代码并触发分析，实时展示进度
  - 运行模式：新增 `--webui-only` 模式，仅启动 Web 服务
  - 解决了 [#70](https://github.com/ZhuLinsen/daily_stock_analysis/issues/70) 的核心需求（提供触发分析的接口）
- ⚙️ GitHub Actions 配置灵活性增强（[#79](https://github.com/ZhuLinsen/daily_stock_analysis/issues/79)）
  - 支持从 Repository Variables 读取非敏感配置（如 STOCK_LIST, GEMINI_MODEL）
  - 保持对 Secrets 的向下兼容

### 修复
- 🐛 修复企业微信/飞书报告截断问题（[#73](https://github.com/ZhuLinsen/daily_stock_analysis/issues/73)）
  - 移除 notification.py 中不必要的长度硬截断逻辑
  - 依赖底层自动分片机制处理长消息
- 🐛 修复 GitHub Workflow 环境变量缺失（[#80](https://github.com/ZhuLinsen/daily_stock_analysis/issues/80)）
  - 修复 `CUSTOM_WEBHOOK_BEARER_TOKEN` 未正确传递到 Runner 的问题

## [1.5.0] - 2026-01-17

### 新增
- 📲 单股推送模式（[#55](https://github.com/ZhuLinsen/daily_stock_analysis/issues/55)）
  - 每分析完一只股票立即推送，不用等全部分析完
  - 命令行参数：`--single-notify`
  - 环境变量：`SINGLE_STOCK_NOTIFY=true`
- 🔐 自定义 Webhook Bearer Token 认证（[#51](https://github.com/ZhuLinsen/daily_stock_analysis/issues/51)）
  - 支持需要 Token 认证的 Webhook 端点
  - 环境变量：`CUSTOM_WEBHOOK_BEARER_TOKEN`

## [1.4.0] - 2026-01-17

### 新增
- 📱 Pushover 推送支持（PR #26）
  - 支持 iOS/Android 跨平台推送
  - 通过 `PUSHOVER_USER_KEY` 和 `PUSHOVER_API_TOKEN` 配置
- 🔍 博查搜索 API 集成（PR #27）
  - 中文搜索优化，支持 AI 摘要
  - 通过 `BOCHA_API_KEYS` 配置
- 📊 Efinance 数据源支持（PR #59）
  - 新增 efinance 作为数据源选项
- 🇭🇰 港股支持（PR #17）
  - 支持 5 位代码或 HK 前缀（如 `hk00700`、`hk1810`）

### 修复
- 🔧 飞书 Markdown 渲染优化（PR #34）
  - 使用交互卡片和格式化器修复渲染问题
- ♻️ 股票列表热重载（PR #42 修复）
  - 分析前自动重载 `STOCK_LIST` 配置
- 🐛 钉钉 Webhook 20KB 限制处理
  - 长消息自动分块发送，避免被截断
- 🔄 AkShare API 重试机制增强
  - 添加失败缓存，避免重复请求失败接口

### 改进
- 📝 README 精简优化
  - 高级配置移至 `docs/full-guide.md`


## [1.3.0] - 2026-01-12

### 新增
- 🔗 自定义 Webhook 支持
  - 支持任意 POST JSON 的 Webhook 端点
  - 自动识别钉钉、Discord、Slack、Bark 等常见服务格式
  - 支持配置多个 Webhook（逗号分隔）
  - 通过 `CUSTOM_WEBHOOK_URLS` 环境变量配置

### 修复
- 📝 企业微信长消息分批发送
  - 解决自选股过多时内容超过 4096 字符限制导致推送失败的问题
  - 智能按股票分析块分割，每批添加分页标记（如 1/3, 2/3）
  - 批次间隔 1 秒，避免触发频率限制

## [1.2.0] - 2026-01-11

### 新增
- 📢 多渠道推送支持
  - 企业微信 Webhook
  - 飞书 Webhook（新增）
  - 邮件 SMTP（新增）
  - 自动识别渠道类型，配置更简单

### 改进
- 统一使用 `NOTIFICATION_URL` 配置，兼容旧的 `WECHAT_WEBHOOK_URL`
- 邮件支持 Markdown 转 HTML 渲染

## [1.1.0] - 2026-01-11

### 新增
- 🤖 OpenAI 兼容 API 支持
  - 支持 DeepSeek、通义千问、Moonshot、智谱 GLM 等
  - Gemini 和 OpenAI 格式二选一
  - 自动降级重试机制

## [1.0.0] - 2026-01-10

### 新增
- 🎯 AI 决策仪表盘分析
  - 一句话核心结论
  - 精确买入/止损/目标点位
  - 检查清单（✅⚠️❌）
  - 分持仓建议（空仓者 vs 持仓者）
- 📊 大盘复盘功能
  - 主要指数行情
  - 涨跌统计
  - 板块涨跌榜
  - AI 生成复盘报告
- 🔍 多数据源支持
  - AkShare（主数据源，免费）
  - Tushare Pro
  - Baostock
  - YFinance
- 📰 新闻搜索服务
  - Tavily API
  - SerpAPI
- 💬 企业微信机器人推送
- ⏰ 定时任务调度
- 🐳 Docker 部署支持
- 🚀 GitHub Actions 零成本部署

### 技术特性
- Gemini AI 模型（gemini-3-flash-preview）
- 429 限流自动重试 + 模型切换
- 请求间延时防封禁
- 多 API Key 负载均衡
- SQLite 本地数据存储

---

[Unreleased]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.32.0...HEAD
[3.32.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.31.0...v3.32.0
[3.31.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.30.0...v3.31.0
[3.30.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.29.0...v3.30.0
[3.29.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.28.0...v3.29.0
[3.28.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.27.0...v3.28.0
[3.27.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.26.1...v3.27.0
[3.26.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.25.0...v3.26.1
[3.25.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.1...v3.25.0
[3.24.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.24.0...v3.24.1
[3.24.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.23.0...v3.24.0
[3.23.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.22.0...v3.23.0
[3.22.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.1...v3.22.0
[3.21.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.21.0...v3.21.1
[3.21.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.20.0...v3.21.0
[3.20.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.19.0...v3.20.0
[3.19.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.18.0...v3.19.0
[3.18.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.1...v3.18.0
[3.17.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.17.0...v3.17.1
[3.17.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.16.0...v3.17.0
[3.16.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.15.0...v3.16.0
[3.15.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.2...v3.15.0
[3.14.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.1...v3.14.2
[3.14.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.14.0...v3.14.1
[3.14.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.13.0...v3.14.0
[3.13.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.12.0...v3.13.0
[3.12.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.11.0...v3.12.0
[3.11.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.1...v3.11.0
[3.10.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.10.0...v3.10.1
[3.10.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.9.0...v3.10.0
[3.9.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.8.0...v3.9.0
[3.8.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.7.0...v3.8.0
[3.7.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.10...v3.5.0
[3.4.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.9...v3.4.10
[3.4.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.8...v3.4.9
[3.4.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.7...v3.4.8
[3.4.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.4.0...v3.4.7
[3.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.22...v3.4.0
[3.3.22]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.3.12...v3.3.22
[3.3.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.11...v3.3.12
[3.2.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v3.2.10...v3.2.11
[2.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.5...v2.3.0
[2.2.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.4...v2.2.5
[2.2.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.3...v2.2.4
[2.2.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.2...v2.2.3
[2.2.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.14...v2.2.0
[2.1.14]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.13...v2.1.14
[2.1.13]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.12...v2.1.13
[2.1.12]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.11...v2.1.12
[2.1.11]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.10...v2.1.11
[2.1.10]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.9...v2.1.10
[2.1.9]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.8...v2.1.9
[2.1.8]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.7...v2.1.8
[2.1.7]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.6...v2.1.7
[2.1.6]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.5...v2.1.6
[2.1.5]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.4...v2.1.5
[2.1.4]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.3...v2.1.4
[2.1.3]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.2...v2.1.3
[2.1.2]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.6.0...v2.0.0
[1.6.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ZhuLinsen/daily_stock_analysis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v1.0.0

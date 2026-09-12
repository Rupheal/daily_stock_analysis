# 港股新闻：香港、美国与欧洲来源

更新日期：2026-09-12。范围：独立修复分支的港股新闻模块；原版 main、行情来源、两个独立股票池均保持原状。没有启动 TOP3 或定时任务。

## 默认运行链路

经济通公司新闻页及公开文章 → 富途中署名明确的境外专业媒体 → 经济通编辑精选/焦点专题 RSS → 香港电台财经 RSS → FT 香港/亚太 RSS。逐源失败隔离，记录错误；有返回但没有近期相关公司新闻时计0条，不冒充接口故障，也不填入过期文章。

读取和解析沿用原生 HTTPS、DNS/私网地址、大小限制；不改 VPN，不关闭 TLS 校验，不使用付费搜索或新增密钥。RSS 只取公开提要；全文遇登录或付费墙不绕过。经济通 RSS 按其个人非商业使用条款保留“《經濟通》新聞”署名。本项目只作用户私人研究，不向公共仓库提交媒体正文。

新浪、东方财富、财联社退出默认港股新闻输入。旧记录仍保留作历史审计，但在本地资讯消费和 SearchService 港股新闻排序时按同一来源规则过滤。富途转载财联社不会被重新归类为香港媒体；来源不明“快讯”、公关稿及社区帖子也不会借转载身份进入专业媒体事实池。

港股个股管线同时停止调用会自动启用大陆NewsNow源的通用刷新入口，改走上述专用适配器；A股及美股原有行为不变。离线测试关闭自动联网，真实抓取步骤单独启用；测试使用UTC发布时间并保留未来日期拒绝规则。

媒体区域表示出版机构/新闻业务来源，不保证服务器或CDN物理位置。路透归为欧洲/国际通讯社；不按 .com 或语言猜测国籍。经济通与香港经济日报、富途与Moomoo、道琼斯与WSJ分别按媒体集团关系处理，不能以不同网址增加独立确认次数。

## 来源清单与实测边界

| 来源 | 区域和用途 | 已核实入口与接入状态 |
| --- | --- | --- |
| [经济通 ETNet](https://www.etnet.com.hk/www/tc/stocks/realtime/quote_news.php?code=1810) | 香港；公司动态、回购、大行评级 | 个股页及文章 HTTP200，明确日期到分钟；已实现公司新闻采集。 |
| [经济通 RSS](https://www.etnet.com.hk/www/tc/news/rss_detail.php) | 香港；大市和焦点线索 | 两个官方RSS各返回20项；本次首屏无近期小米公司匹配，不用无关内容填数。 |
| [香港电台 RTHK](https://news.rthk.hk/rthk/ch/rss.htm) | 香港；财经和政策、市场收评 | 官方财经RSS返回20项；使用已观测到的rthk9官方重定向目的地址，保留DNS保护。 |
| [AASTOCKS](https://www.aastocks.com/tc/stocks/analysis/stock-aafn/01810/0/hk-stock-news/1) | 香港；港股专业快讯与研报摘要 | 直连网页此次403；现有富途公开页含署名AASTOCKS内容，通过聚合渠道读取并保留原媒体身份。 |
| [信报 HKEJ](https://www.hkej.com/instantnews) | 香港；港股直击、香港财经 | 公开新闻列表可读；列为后备研究入口，尚未添加自动解析器，深度内容权限未核实。 |
| [SCMP 港股专题](https://www.scmp.com/topics/hong-kong-stock-exchange) | 香港；国际资金视角 | 本次403，未接入自动采集，未购买订阅。 |
| [道琼斯 / WSJ](https://www.wsj.com/market-data/quotes/HK/XHKG/1810) | 美国；公司与机构新闻 | 富途含署名道琼斯小米报道。WSJ报价页可读，但新闻栏空，不能据此判断公司两年无新闻。用户已有WSJ订阅不等于DSA获得API/全文自动读取权限。 |
| [MT Newswires（富途转载示例）](https://news.futunn.com/post/79127081/zhongce-rubber-to-supply-tires-for-xiaomi-s-pengcheng-n70) | 美国；公司与供应链 | 富途公开页可解析署名及时间；同一篇转载仍只是一条证据。 |
| [CNBC](https://www.cnbc.com/asia-markets/)、[Bloomberg](https://www.bloomberg.com/markets/stocks) | 美国；亚洲市场、全球资金和利率 | 当前网页工具受robots访问限制，保留研究候选，未宣称自动接通。 |
| [FT 香港 RSS](https://www.ft.com/hong-kong?format=rss)、[FT 亚太 RSS](https://www.ft.com/asia-pacific?format=rss) | 英国；香港/亚洲市场、跨境资本和公司事件 | 两个官方域名RSS均为HTTP200有效XML，各25项；已接入公开提要。此次近期小米匹配数量应以运行日志为准，不能承诺每天有个股报道；不获取付费全文。 |
| [Reuters 小米](https://www.reuters.com/markets/companies/1810.HK/) | 欧洲/国际；公司重大事件、监管风险 | 网页搜索可找到9月9日印度调查建议报道；程序直连公司页401，未把全文或直接API计作接通，可使用明确署名的公开转载或人工核验。 |
| [HKEXnews](https://www.hkexnews.hk/index.htm) | 香港；交易所披露核验 | 官方查询入口可读。公司公告自动下载仍未完成；交易所集团新闻RSS不是所有上市公司的公告流。 |

## 社交平台：研究入口与新闻事实隔离

| 来源 | 验证结果 | 使用边界 |
| --- | --- | --- |
| [TradingView HKEX:1810 Ideas](https://www.tradingview.com/symbols/HKEX-1810/ideas/) | 可读到小米社区观点 | 个帖需再核发布日期、作者和币种；不把旧技术分析、目标价或点赞数当成当前行情、概率或机构共识。未自动评分。 |
| [Reddit r/HKstocks](https://www.reddit.com/r/HKstocks/) | 社区页面可读 | 需验证近期帖子量和公司关联；没有验证API权限，不承诺全量或实时监控。 |
| [Stocktwits XIACY](https://stocktwits.com/symbol/XIACY) | 标的页面可读 | XIACY是美国场外证券入口，不能与01810港元股价混算；未接通帖子API或情绪打分。 |
| [Moomoo 01810 社区](https://www.moomoo.com/stock/01810-HK/community) | 本次403/访问频率限制 | 与富途同系，不算独立媒体。暂停自动接入，不反复请求或切IP绕过限制。 |

社交帖子仅作待核线索和情绪背景；不能单独满足新闻证据验收，也不能触发交易结论。此阶段继续保持原版港股不使用US-only社交采集服务的边界。

## 验收与费用

已在当前环境取到经济通、RTHK、FT和富途公开返回，并使用真实样本验证解析；新增7项离线边界测试通过。完整原生DNS请求、数据库、SearchService和DSA消费者将在07工作流进行验收；本次最终结果与费用以交付运行记录为准。

验收门槛：不少于3条近期公司关联新闻、至少2个出版机构身份；原媒体及发布时间保留；旧大陆来源哨兵不得出现在DSA上下文；每个信源都有失败或有效条数诊断。零相关新闻与抓取失败必须区分。通过这些检查不等于新闻全文逐项事实核验或投资结论验收通过。

新增模型调用0；未使用付费搜索、未购买媒体或API订阅。GitHub Actions实际账单不可核实，不将全部运行费用宣称为零。

回滚：恢复本次改动前修复分支 a48580fd02d8852bc79047ecbbcbd919c9ed2cce 中相关文件；不对main执行覆盖或强制推送。本文为中文运行方案，无英文对应文件。完整后端CI未在本地运行，因为当前Python3.12环境无法加载先前Python3.11二进制依赖；使用GitHub独立3.11环境验证实际运行。

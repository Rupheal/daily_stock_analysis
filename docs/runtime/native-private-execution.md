# O 原生私密执行验收接续

Run: TRI-DSA-EXEC-20260914-009。基线为已验收运行分支
6ac18ddc86a2a3011d056e2e9a5a9aa188d5f17f；本地候选改动尚未云端验收。

执行顺序：O 单股原生运行与原始证据私密保存均通过，才进入 U 正式逐股执行验收；
只有合格 BUY 才测试真实可验证价格的模拟入场。准备检查不等于正式验收。

`scripts/run_hk_original_private_probe.py` 仅包装已有原生观察器。
冻结上游 089d9d26d68f8b839ea5a74a3784e4402925f8b7，不能修改提示词或评分。
当前只支持单股观察器，不生成全池排名。上游代码、main 与正式运行分支未修改。

以下为可选私密主机入口，不是要求用户部署新主机。既有 GitHub 云端原生工作流
12 已使用 secrets.DEEPSEEK_API_KEY，并映射到 LLM_DEEPSEEK_API_KEY，
BASE_URL 为 https://api.deepseek.com，模型配置为 deepseek-flash。
当前 Work 环境缺配置不代表云端模型不可用。旧工作流因为公开原始附件而不能重开；
42 工作流只做离线测试与既有密钥是否配置的布尔检查，不读出密钥、不调用模型、
不上传原始附件。安全私密保存目的地尚未核实，不能用这个准备工作流宣布原生验收。

若使用可选私密运行主机，须事先配置 LLM_DEEPSEEK_API_KEY、LLM_DEEPSEEK_BASE_URL、
LLM_DEEPSEEK_MODELS。不得从 GitHub secrets 导出密钥，也不得在聊天中粘贴密钥。
包装器拒绝 GitHub Actions；不提供公开日志或附件输出路径。
只读预检命令：

```sh
python scripts/run_hk_original_private_probe.py --checkout /private/original \
  --expected-commit 089d9d26d68f8b839ea5a74a3784e4402925f8b7 \
  --output /private/evidence/new-run --run-id TRI-DSA-EXEC-20260914-009 --check-only
```

真实运行还须提供已校验 preflight 与按余额核实的本轮预算。
所有原始输出只落本地私密目录；manifest 本身不证明已持久保存。
原始输出私密上传、读取回验、哈希一致和人工语义复核全部完成后才可验收。
目前只有合成 JSON 的保存/文本回读通过，既有二进制下载仍返回 HTTP502。
尚无真实模型调用，不得把探针记为 O 验收通过。

U 准备脚本 `scripts/dsa_u_execution_audit.py` 保留45股分母和逐源收据，
仅做不复权日线诊断；0.005 为既有诊断阈值，不构成执行许可。
2026-09-14 本次 Yahoo 当日日线几何45/45通过，腾讯原始 day 请求45/45返回
bad params。单股替代请求仅返回 qfqday，不能冒充原始 day。
上交所买入名单44/45仅为单市场核对；不据此声称沪深并集资格已完成。
新闻、资金潮汐、正式技术结论、费用/汇率/整手和交易方案均待验收。
源抓取在16:30以后，不属于本轮收市截止前可用证据，不能回填既有快照。

回滚：删除这两个新脚本及其测试与本文即可；未接入现有工作流、生产入口或模拟账。

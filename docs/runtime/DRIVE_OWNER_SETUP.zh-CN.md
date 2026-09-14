# DSA Drive 限定授权配置（Run013）

状态：代码及离线验证完成；真实Google授权及runner恢复验收待Owner配置。此文不是连接成功回执。

## 最小Owner操作

复用现有Google账号及Drive，不购买存储、不新建服务器、不配置NAS。

1. 在 https://console.cloud.google.com/ 选择已有项目；若没有，可建立用于本次OAuth配置的项目。进入“APIs & Services → Library”，启用 Google Drive API 和 Google Picker API。无需开启付费计算资源或购买订阅；若页面要求付费升级，暂停并报告。
2. “Google Auth platform → Branding / Audience / Data Access”：建立自用授权应用，Audience按账号类型选择；个人账号使用External，在Testing阶段只添加自己的Google账号为测试用户。权限仅添加 `https://www.googleapis.com/auth/drive.file`，不添加整盘drive或drive.readonly权限。Testing/发布状态可能影响refresh token有效期；本次短期验收可用Testing，长期无人值守需另核验Google应用发布与token续期要求，不能宣称永久可用。
3. “Google Auth platform → Clients → Create client → Desktop app”，下载客户端JSON，仅放在自己电脑的非仓库目录。不要上传至Drive归档、GitHub或聊天。
4. 在自己的电脑下载本修复分支的 `scripts/dsa_drive_authorize.py` 和 `scripts/dsa_drive_store.py` 到同一目录。已有Python可复用；运行 `python -m pip install httpx`，再执行下列命令。将占位符替换为本机文件路径及已经确认的目标folder ID（来自目标Drive文件夹URL），不要将凭据作为命令参数。

```powershell
python dsa_drive_authorize.py --client-json "C:\private\client_secret_downloaded.json" --folder-id "<DSA_PRIVATE_EVIDENCE_FOLDER_ID>" --output "C:\private\dsa-drive-credentials.json"
```

浏览器会打开Google官方授权与文件夹选择页，只选择既有 `TRIDENT_BACKUP/DSA_PRIVATE_EVIDENCE`。脚本使用state和PKCE、仅本机回调、不记录授权码；核验权限后才将凭据保存到指定本机文件。浏览器交互尚未实测，若提示取消、文件夹不可选或授权失败，保留错误代码并停止，不扩大权限。

5. 打开 `Rupheal/daily_stock_analysis → Settings → Secrets and variables → Actions → Repository secrets → New repository secret`，将本机生成JSON中的四个值分别存入同名Secrets：
   - `DSA_DRIVE_FOLDER_ID`
   - `DSA_DRIVE_CLIENT_ID`
   - `DSA_DRIVE_CLIENT_SECRET`
   - `DSA_DRIVE_REFRESH_TOKEN`
   保留原有DeepSeek配置。凭据只进入Secrets安全页面，不粘贴到聊天。不要给公共仓库贡献者写权限或让不可信PR运行带Secrets的任务。
6. 告知“Drive四项配置已完成”（不附凭据）。接续执行者触发新的44号准备运行，先验证runner原始字节上传、独立读回、哈希及新目录恢复；然后通过连接器核对该合成文件。只有通过后才将既有43号arm置true并执行一次必要O原生单股。

`drive.file` 是Google按应用/所选文件授权，代码另将写入限制在固定folder。它不是服务端不可修改权限：owner仍可编辑/删除，单写者串行约束、只追加和哈希检测由本实现承担，不宣称WORM存储。当前版本仅支持owner-only的My Drive文件夹，不支持Shared Drive或其他共同编辑者。

## 费用及撤销

本轮没有新增模型费用、订阅或付费服务。占用已有Drive空间与GitHub Actions权益；当前无法精确读取平台账单，不承诺所有平台费用为零。撤销时在Google账号第三方应用访问中撤销本应用授权，并删除四项DSA_DRIVE Secrets；不删除既有原始证据。

## 当前实现范围

- 单个未压缩证据包最多4MiB；更大包明确拒绝，不自动分割或写入GitHub。下一步若原生单股超过此边界，先评估可复用的分块/续传，再按新范围登记，不截断原件。
- 原始字节归档保留JSON/数据库/ZIP内部格式；外部存为opaque `.bin`对象，内含ZIP及MANIFEST。不转换为Google文档。
- 同Artifact ID和内容重试校验已有文件，不再上传；不同内容拒绝；并发写者由两个工作流共享concurrency group序列化。不提供跨未知外部写者的事务保证。
- POST不自动重试；模糊失败需重新查Artifact ID并对账，不能盲目重发。
- 先做权限核验再保存；保存后再次核验、按version/sha256读回。故障只发布错误代码，不公开请求体/响应体/原件路径。
- 所有正式artifact需显式填来源/取得时间与父artifact；合成探针时间可空并标明非市场证据。生成摘要不能替代原件。

## 官方依据

- https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- https://developers.google.com/workspace/drive/api/guides/manage-uploads
- https://developers.google.com/identity/protocols/oauth2/web-server

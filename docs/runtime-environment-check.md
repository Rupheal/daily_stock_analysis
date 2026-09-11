# Runtime environment check / 运行环境检查

Run `DSA environment check (no model calls)` manually from GitHub Actions. It installs upstream requirements under Python 3.11 and checks dependencies, CLI startup and analysis/screening imports.

The workflow checks out unchanged upstream commit `089d9d26d68f8b839ea5a74a3784e4402925f8b7`. No model secrets, stock analysis or notifications are configured. A successful run verifies the runtime only; market data and model calls require separate acceptance.

在 GitHub Actions 手动执行环境检查。成功仅代表依赖、启动及模块导入正常，不代表行情或模型可用。其他继承工作流保持停用；单股试跑与正式定时任务后续配置。

Rollback / 回滚：disable or delete `.github/workflows/00-environment-check.yml`，停用或删除此新增工作流即可。原版策略、提示词和评分保持不变。

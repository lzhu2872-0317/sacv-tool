# SACV-Tool 1.2.4

- 修复“题名劫持”漏洞：真实 DOI、作者和年份不能再掩盖与注册表严重冲突的引用题名；新增 `DOI_EXACT_TITLE_CONFLICT`。
- DOI 精确命中的证据优先级改为：多字段冲突、题名冲突、无题名时的作者+年份补足、解析不确定。
- Benchmark 新增 `benchmark-predictions.csv`，保留记录 ID、真实标签、攻击类型、预测状态和判断是否正确。
- `benchmark-metrics.json` 新增按真实标签的状态分布和按攻击类型的自动通过率。
- 新增 `--reuse-results` 离线复算，可复用旧 `sacv-results.json` 中的注册表证据，规则升级后无需重新进行数百次网络请求。
- 在当前 1,000 条数据上离线复算：无效引用误通过由 122 降至 0；有效引用 precision 由 0.798347 升至 1.0，recall 保持 0.966；Ghost Citation recall 由 0.756 升至 1.0，F1 由 0.844693 升至 0.983284。
- 自动化测试总数为 49。

上述基准数据的无效样本仍标记为 `pending_double_review`，正式论文报告中应说明标签尚待双人核验，不应把当前结果描述为最终外部验证。

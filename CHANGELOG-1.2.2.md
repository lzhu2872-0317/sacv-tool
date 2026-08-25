# SACV-Tool 1.2.2

## 参考文献提取修复

- 在双栏判断之前检测并移除 Word 导出的连续边栏行号。
- 防止 472、473、474 等行号被误判为 PDF 左栏，破坏单栏参考文献阅读顺序。
- 保留正常编号参考文献；规则只处理密集、连续、对齐的边栏数字流。
- “测试幻觉1.pdf”由错误的 8 条恢复为人工确认的 13 条，并正确保留跨页文献。

## 幻觉候选修复

- 搜索 API 返回年份相同但题名、作者均弱匹配的无关记录时，不再当作真实候选。
- 高解析置信度、无 DOI/URL 的学术引用在多个注册表均无有意义匹配时，进入 `potential_hallucination`。
- 若一个注册表暂时故障、另一个仅返回弱匹配，系统以 `NO_MEANINGFUL_MATCH_PARTIAL_REGISTRY_OUTAGE` 提醒人工核查，提高安全场景下的 Recall。
- 无标识符且证据不足时不再虚构 `metadata_mismatch`，改为 `review / WEAK_REGISTRY_CANDIDATE`。

## 回归结果

- “测试幻觉1.pdf”：13 条，Goldman 2026 正确进入 `potential_hallucination`。
- 已发表论文样本：132 条。
- BIM 样本：59 条。
- 自动化测试：44 项通过。

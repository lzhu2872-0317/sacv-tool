# SACV-Tool 1.2.1

## 重点修复

- 修复 Chicago 引号题名、单作者引用、arXiv 引用和大写单词跨行断字的解析。
- DOI 精确命中不再因局部题名解析噪声被大面积误报；原始引用题名命中，或作者与年份共同印证即可自动确认。
- 只有解析可信且至少两项核心元数据明显冲突时，精确 DOI 才会进入 `metadata_mismatch`。
- 新增 `web_reachable`，用于“网址可访问但页面题名不足”的网页来源。
- 新增 `web_access_restricted`，将 HTTP 401/403/429 与真正的网络或程序错误分开。
- 网页核验增加浏览器型请求头、HTML `h1` 回退和 PDF 元数据/首页题名读取。
- 界面新增 `Auto-confirmed` 总数，避免用户只看学术 `Verified` 而低估已确认来源。

## 对 132 条已发表论文样本的影响

在不重新发起数据库查询、直接复用原 CSV 中已取得的候选元数据进行确定性重分类时：

- `verified`：26 → 57；
- `web_validated`：25；
- `Auto-confirmed`：51 → 82（62.1%）；
- `metadata_mismatch`：27 → 3；
- `review`：23 → 4；
- 原 15 个 HTTP 403 `error` 改为 `web_access_restricted`；
- 原 19 个“网页可访问但无题名” `review` 改为 `web_reachable`；
- 真正的网络/提供方 `error`：17 → 2。

`web_reachable` 和 `web_access_restricted` 仍需人工确认，但不再与程序错误或元数据冲突混为一类。

## 验证

- 自动化测试：42 项通过，并连续运行两次；
- 继续保留单栏/双栏 PDF、参考文献终止边界、真实页码、拆分/合并诊断和最低证据门槛的回归测试。

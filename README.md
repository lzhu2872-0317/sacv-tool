# SACV-Tool

SACV-Tool（Semi-Automated Citation Veracity Tool）是一个面向研究生、图书馆员和机构知识库管理员的半自动参考文献真实性核验工具。它从 PDF 或纯文本中提取参考文献，先识别来源类型，再将期刊/会议路由到 Crossref、OpenAlex（可选 PubMed），将政策、机构报告和网页路由到 URL/网页元数据核验，最后输出分级证据与人工复核项。

这个版本已经实现可运行的研究原型，而不只是演示脚本：

- 单栏/双栏及带 Word 连续行号的 PDF、TXT、Markdown 参考文献提取，并保留每条引用的真实起止页；
- 过滤下载水印、页眉页脚、论文自身 DOI，并在 `References` 到 `Appendix`/作者简介之间精确截取；
- 跨行引用重建、粘连引用拆分、断裂引用诊断，以及 Appendix/附录自动终止；
- 支持机构作者、单词机构名、完整发布日期和 `n.d.` 无日期网页来源；
- APA、Chicago（含引号题名）、单作者和 arXiv 等常见引用格式的作者、年份、题名、期刊和 DOI 解析；
- Crossref DOI 精确查询、OpenAlex 回退检索与 bibliographic search；
- 政策、机构和普通网页执行 URL 可访问性、软 404、HTML/PDF 元数据与页面标题核验，并单列服务器拒绝访问；
- 可选 PubMed E-utilities 回退查询；
- 0.85 默认阈值、最低证据门槛和 DOI 劫持/元数据错配检测；
- 符合 API 限流的异步批处理、自动重试和本地缓存；
- 人工复核（HITL）字段；
- CSV、JSON、独立 HTML 审计报告；
- 带标签金标准数据集的 Precision、Recall、F1、Ghost-detection 指标和 Hallucination Rate；
- 命令行和 Streamlit 本地网页界面；
- 自动化单元测试。

## 1. 环境要求

- Windows 10/11、macOS 或 Linux；
- Python 3.11 或更高版本；
- 可访问 `api.crossref.org`、`api.openalex.org` 和参考文献中的外部网页；使用 PubMed 时还需访问 `eutils.ncbi.nlm.nih.gov`；
- 建议准备真实联系邮箱。Crossref 建议在请求中提供 `mailto` 以进入 polite pool；当前列表查询限制为 public pool 1 次/秒、polite pool 3 次/秒。程序会自动按此节流。[Crossref 官方说明](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)

PubMed 不带 API Key 时应限制在每秒 3 次请求；带 Key 时默认可到每秒 10 次。本程序同样自动节流。[NCBI E-utilities 官方说明](https://www.ncbi.nlm.nih.gov/books/NBK25497/)

## 2. Windows 安装步骤（CMD）

打开 CMD，进入项目目录：

```bat
cd /d "C:\path\to\sacv-tool"
```

创建并激活独立虚拟环境：

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
```

安装项目及测试依赖：

```bat
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

验证安装：

```bat
sacv --help
python -m pytest -q
```

PowerShell 对应的激活命令是 `.\.venv\Scripts\Activate.ps1`；macOS/Linux 使用 `source .venv/bin/activate`。

## 3. 最快运行：本地网页界面

```powershell
sacv serve
```

命令会显示本地地址；在浏览器打开 `http://localhost:8501`。操作顺序：

1. 在左侧输入真实联系邮箱；
2. 保持默认阈值 `0.85`；
3. 保持 OpenAlex 和网页核验启用，医学文献可按需启用 PubMed；
4. 上传包含 `References` 或 `Bibliography` 标题的 PDF，或上传一行/一段一条引用的 TXT；
5. 点击 **Run citation audit**；
6. 先查看 `Auto-confirmed` 总数，再在结果表中区分 `verified`、`web_validated`、`web_reachable`、`web_access_restricted`、`review`、`not_found`、`metadata_mismatch`、`potential_hallucination`、`parse_error`、`error`；
7. 在 `reviewer_decision` 中人工确认，再下载 CSV、JSON 或 HTML 报告。

网页服务只监听本机；按 `Ctrl+C` 停止。

## 4. 命令行核验

先用自带样例验证：

```powershell
sacv verify data\sample_references.txt --email "your.name@um.edu.my" --output runs\sample
```

核验真实论文 PDF：

```powershell
sacv verify "C:\path\to\thesis.pdf" --email "your.name@um.edu.my" --output runs\thesis-001
```

同时启用 PubMed：

```powershell
sacv verify "C:\path\to\thesis.pdf" --email "your.name@um.edu.my" --pubmed --output runs\thesis-001
```

每次运行会产生：

- `sacv-results.csv`：适合 Excel/SPSS 后续处理；
- `sacv-results.json`：完整结构化数据；
- `sacv-report.html`：可直接在浏览器打开的审计报告；
- `.sacv-cache.json`：请求缓存，重复运行时减少 API 流量。

## 5. 运行金标准 Benchmark

CSV 必须至少包含标签列 `label`，引用正文列可以命名为 `citation` 或 `citation_text`：

```csv
citation,label
"完整参考文献字符串",valid
"完整参考文献字符串",invalid
```

运行自带的小型演示集：

```powershell
sacv benchmark data\sample_benchmark.csv --email "your.name@um.edu.my" --output runs\benchmark-sample
```

替换为研究所需的 1,000 条人工核验金标准数据：

```powershell
sacv benchmark "C:\path\to\SACV-Benchmark-1000.csv" --email "your.name@um.edu.my" --output runs\benchmark-1000
```

额外输出 `benchmark-metrics.json` 和 `benchmark-predictions.csv`。后者保留每条记录的真实标签、攻击类型、预测状态、是否自动通过和是否判断正确，便于直接定位误差。指标文件同时报告：

- `precision_valid` / `recall_valid` / `f1_valid`：把“真实引用”作为正类；
- `precision_ghost_detection` / `recall_ghost_detection` / `f1_ghost_detection`：把“Ghost Citation”作为目标类；
- `hallucination_rate`：被正确拦截的无效引用占有效评测样本总数的比例。
- `status_by_ground_truth`：真实/无效两类在各状态中的数量；
- `by_mutation_type`：每一种攻击方式的自动通过率和复核率。

这样避免了研究文稿中 TP/TN 叙述容易混淆的问题。`review` 会按“未自动通过”计入评测，API 全部失败的 `error` 则从指标分母排除并单独计数。

## 6. 结果判读

- `verified`：DOI 与描述性元数据一致，或题名、作者/年份等至少两类证据达到通过条件；
- `web_validated` / `grey_literature_validated`：有效官方 URL 的网页标题与引用题名相符；
- `web_reachable`：URL 可正常访问，但页面没有足够题名元数据；它不是数据库错误，也不计入自动确认；
- `web_access_restricted`：服务器返回 401/403/429，说明站点存在但限制自动访问；它不是程序崩溃，也仍需人工打开核对；
- `identifier_verified_parse_uncertain`：DOI 精确存在，但本地解析质量不足，不能盲目自动通过；
- `review`：证据不足或处于边界区，需要人工核对；只有年份匹配时固定进入此状态；
- `not_found`：当前启用的注册表没有找到候选结果，不代表引用虚假；
- `metadata_mismatch`：DOI 或题名/作者等元数据存在明显冲突；
- `potential_hallucination`：高质量、无 DOI/URL 的学术引用在多个学术库没有有意义匹配；只有年份相同的无关结果不算命中。若一个注册表暂时故障，另一个只返回弱匹配，也会以明确的“部分注册表故障”理由进入此人工复核状态；它不是自动学术不端结论；
- `parse_error`：引用在 PDF 中疑似仍有断裂、粘连或附录污染，应先检查解析结果；
- `error`：所有启用的数据源均因网络、限流或服务异常失败。

综合分固定按题名 65%、作者 20%、年份 10%、期刊 5% 加权。缺失字段不再重新归一化，因此只命中年份的最高分是 `0.10`，不会被误判为 `verified`。自动通过还必须满足最低证据门槛，不能只依赖总分。

DOI 精确命中也不会盲目放行：注册表题名能在原始引用中找到，或解析题名与注册表题名相符时进入 `verified`。如果存在高可信解析题名且与 DOI 注册表题名严重冲突，即使作者和年份相同，也进入 `metadata_mismatch` 并记录 `DOI_EXACT_TITLE_CONFLICT`，从而阻止“真实 DOI + 被替换题名”的标识符劫持。只有没有可用题名时，作者与年份共同印证才可补足证据。解析证据仍不足时进入 `identifier_verified_parse_uncertain`。显式 DOI 不相同则标记 `DOI_CONFLICT`。`conflict` 和 `flagged` 仅为旧版结果兼容值。

修改规则后可复用已经完成的注册表证据，无需再次等待网络：

```powershell
sacv benchmark "C:\path\to\SACV-Benchmark-1000.csv" --output runs\benchmark-replay --reuse-results "C:\path\to\old-run\sacv-results.json"
```

离线复算会先核对记录总数、顺序和引用正文；不一致时立即停止，避免标签与预测错位。

解析器会在 DOI、URL 或句号后识别新的“作者 + 年份”起点，将误粘连的多篇引用拆开；会把明显的续行片段接回上一条；遇到 `Appendix`、`Appendices`、`Annex` 或 `附录` 标题时停止。CSV 中的 `source_page` 和 `source_end_page` 分别表示该条引用开始和结束的 PDF 页，`parse_flags` 记录自动修复或仍需人工关注的解析问题。

## 7. 研究数据还需要什么

代码可以独立运行，但要完成论文中正式的 1,000 条评测，你仍需准备：

1. 500 条经人工确认的真实引用；
2. 500 条经人工确认的 fabricated/ghost citations；
3. 每条唯一标签 `valid` 或 `invalid`；
4. 最好记录来源、学科、语言、人工核验人和核验日期，另存为扩展列。

自带 `sample_benchmark.csv` 只用于证明流程可运行，不能替代论文实验数据。

## 8. 已知边界与伦理要求

- Crossref/OpenAlex/PubMed 未收录并不等于引用造假，灰色文献、本地期刊、图书章节和非拉丁文字元数据更容易出现 false flag；
- 相似度是字符级证据，不是语义真理判断；
- 本工具只能作为 librarian/researcher 的决策支持，不应自动认定学术不端；
- 上传到本地网页界面的文件只在本机临时目录处理；实时核验时只把解析后的引用查询发送给注册表；
- NCBI 要求应用提供 `tool` 与有效 `email`，大规模任务应遵守其时间与批处理建议。

## 9. 项目结构

```text
sacv-tool/
├─ data/                  # 样例引用与 benchmark
├─ src/sacv_tool/
│  ├─ extractor.py       # PDF/TXT 提取
│  ├─ parser.py          # 引用字段解析
│  ├─ providers/         # Crossref / OpenAlex / PubMed / Web
│  ├─ matching.py        # Levenshtein 评分与 DOI 错配检测
│  ├─ verifier.py        # 异步核验、缓存、分类
│  ├─ reports.py         # CSV/JSON/HTML
│  ├─ benchmark.py       # 混淆矩阵与指标
│  ├─ cli.py             # 命令行
│  └─ webapp.py          # Streamlit UI
└─ tests/                 # 自动化测试
```

## 10. 常见问题

**没有提取到引用**：确认 PDF 是可搜索文本而非纯扫描图片，并且参考文献部分有 `References`、`Bibliography` 或 `Works Cited` 标题。扫描件需要先 OCR。

**升级后仍看到旧结果**：旧 CSV 不会自动重算。停止服务后重新执行 `sacv serve`，再次上传原 PDF 并运行核验。不要用新程序解释旧版导出的 `flagged` 数量。

**大量 429 或 error**：填写真实邮箱、降低并发、保留缓存并稍后重试。程序已自动限速，但共享 IP/邮箱仍可能受全局配额影响。

**PowerShell 不允许激活脚本**：只对当前窗口执行 `Set-ExecutionPolicy -Scope Process Bypass`，关闭窗口后自动恢复。

**pytest 显示 `WinError 5` 或无权访问 `AppData\\Local\\Temp\\pytest-of-*`**：1.2.5 会强制使用项目内的 `.sacv-test-tmp`，并且相关回归测试不再依赖系统临时目录；更新后直接运行：

```bat
python -m pytest -q
```

**想清空缓存重新核验**：关闭正在运行的程序后，删除对应运行目录中的 `.sacv-cache.json`；其他报告不会受影响。

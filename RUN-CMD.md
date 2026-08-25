# Windows CMD 运行步骤

## 第一次安装

打开 CMD：

```bat
cd /d "解压后的完整路径\sacv-tool"
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m pytest -q
sacv serve
```

测试应显示 `49 passed`。浏览器打开 `http://localhost:8501`；停止服务按 `Ctrl+C`。

## 已有旧版本时

1. 在旧服务窗口按 `Ctrl+C`。
2. 将 1.2.5 解压到一个新目录，不要把旧 `.venv`、`.sacv-cache.json` 或旧 CSV 混入新目录。
3. 在新目录按“第一次安装”重新创建 `.venv` 并安装。
4. 测试通过后再上传同一 PDF 重新检测；旧 CSV 不会自动改变。

## 命令行检测 PDF

```bat
sacv verify "C:\完整路径\论文.pdf" --email "你的邮箱" --output "runs\paper-001"
```

默认启用 OpenAlex 和网页核验。医学文献可加 `--pubmed`。如果只想临时关闭某一路径，可使用 `--no-openalex` 或 `--no-web-validation`。

## 结果文件

`runs\paper-001` 中会生成 CSV、JSON、HTML 和本地缓存。重点状态包括：

- `verified`：学术元数据充分一致；
- `web_validated` / `grey_literature_validated`：URL 和网页题名一致；
- `web_reachable`：网址可访问，但页面题名证据不足；
- `web_access_restricted`：服务器存在但拒绝或限制自动访问（401/403/429）；
- `identifier_verified_parse_uncertain`：DOI 存在，但解析证据不足；
- `review`：需要人工核对；
- `not_found`：当前数据源未找到，不等于虚构；
- `metadata_mismatch`：标识符或描述元数据冲突；
- `potential_hallucination`：至少两个学术库均无有意义匹配，仍需人工确认；
- `parse_error` / `error`：解析或数据源运行错误。

## 直接运行 1,000 条 Benchmark

1.2.5 可直接识别 `SACV-Benchmark-1000.csv` 的 `citation_text` 和 `label` 列：

```bat
sacv benchmark "C:\Users\hp\Documents\Codex\2026-08-18\new-chat-2\outputs\SACV-Benchmark-1000.csv" --email "你的真实邮箱" --output "runs\benchmark-1000-v125"
```

保持 CMD 窗口开启直到进度达到 100%。中断后再次运行相同命令会复用输出目录中的 `.sacv-cache.json`。结果位于 `runs\benchmark-1000-v125`，重点查看 `benchmark-metrics.json`、`benchmark-predictions.csv` 和 `sacv-results.csv`。

如果已经有旧版完整结果，只想用 1.2.5 的新规则重新计算，不要再次访问 Crossref/OpenAlex：

```bat
sacv benchmark "C:\Users\hp\Documents\Codex\2026-08-18\new-chat-2\outputs\SACV-Benchmark-1000.csv" --output "runs\benchmark-1000-v125-replay" --reuse-results "C:\旧运行目录\sacv-results.json"
```

这条命令通常几秒内完成，并生成新的指标、逐条预测 CSV、JSON 和 HTML。

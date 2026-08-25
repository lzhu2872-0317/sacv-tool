# SACV-Tool 1.2.5

- 修复部分 Windows 账户无法访问 `C:\Users\<user>\AppData\Local\Temp\pytest-of-*` 时出现的 `WinError 5`。
- pytest 现在固定使用项目目录内的 `.sacv-test-tmp`。
- 两项 Benchmark 回归测试改为直接使用项目内唯一临时路径，不再依赖 pytest 的系统 `tmp_path` fixture。
- 此修复只影响自动化测试的临时文件位置，不改变 1.2.4 的引用解析、验证规则和 Benchmark 指标。
- 自动化测试仍为 49 项。

# ToolInfra

[English](README.md)

ToolInfra 是一个面向 LLM 代理的轻量级、可扩展工具层。它专注于清晰的契约（schema、文档）、可靠的执行（沙箱优先的 Python 运行器与 Web 工具），以及可选的基础设施支持（缓存、端口转发、MCP 暴露等），目标是在不引入治理负担的前提下持续演进。

## 项目亮点

- **结构化注册表**：`tool_core` 负责注册、校验与调用工具，支持 JSON Schema（或安全兜底）与缓存感知执行。
- **可直接使用的工具**：Python 执行器、基于 Serper 的搜索工具，以及结合 Jina Reader + HTML 解析的访问工具（支持可选 LLM 摘要）。
- **可插拔适配器**：缓存后端（内存、SQLite、MySQL）、摘要组件，以及后续的端口转发/MCP 集成。
- **测试与示例齐备**：`tests/` 覆盖核心逻辑，`examples/` 提供参考流程。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `tool_core/` | 注册表、缓存适配器、摘要组件及公共基元。 |
| `tools/` | 具体工具实现（`python_tool`、`search_tool`、`visit_tool`）。 |
| `tests/` | 单元/集成测试（注册表、工具、缓存、摘要器）。 |
| `config/` | 缓存与摘要器示例配置。 |
| `examples/` | 展示如何调用注册表的脚本。 |
| `tool_module_development.md` | 设计与实现指南。 |
| `changelog.md` | 每日变更记录。 |

## 快速开始

```bash
git clone <repo-url>
cd ToolInfra
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.template .env
# 如需启用缓存
cp config/cache.example.json config/cache.json
# 如需启用摘要器
cp config/summary.example.json config/summary.json
# 如需调整 MCP 服务
cp config/mcp.example.json config/mcp.json
```

根据需要填写 `.env`（如沙箱端点、API Key）。如在 Linux 遇到 sandbox 权限问题，可使用 CLI 提供的提权运行方式。

### 运行测试

```bash
python -m pytest
```

以下套件需要额外配置：

- `SERPER_API_KEY`：真实 `web_search` / `scholar_search` 测试。
- `RUN_VISIT_INTEGRATION=1`：访问真实网页。
- `SUMMARIZER_ENABLED=true` + 配置 `config/summary.json` + `RUN_SUMMARIZER_INTEGRATION=1`：调用真实摘要服务。

### 启动 MCP 服务

1. 安装依赖并配置 `.env`。
2. 根据需要调整 `config/mcp.json` 或设置 `MCP_CONFIG_PATH`。
3. 启动服务，例如：

```bash
python -m mcp_server --transport streamable-http --host 0.0.0.0 --port 8080
```

如需提供给 Claude Desktop 等基于 STDIO 的宿主，可改用：

```bash
python -m mcp_server --transport stdio
```

然后在客户端配置中添加该命令。更多背景与操作说明见 `docs/mcp/`。

快速验证 MCP 客户端可以参考：
- `examples/responses_api_demo.py`：通过 OpenAI Responses API 调用 MCP（默认读取 `config/mcp.json`，可用 `RESPONSES_MCP_URL` / `RESPONSES_MCP_TOKEN` 覆盖）。
- `tests/mcp_client_demo.py`：使用官方 FastMCP 客户端发起 `list_tools` / `call_tool`。

## 关键配置

| 功能 | 配置文件 / 环境变量 | 说明 |
| --- | --- | --- |
| 缓存 | `.env` (`CACHE_*`)、`config/cache*.json` | 支持内存、SQLite、MySQL。 |
| 摘要器 | `.env` (`SUMMARIZER_ENABLED`, `SUMMARIZER_CONFIG_PATH`)、`config/summary.json` | 控制 visit 工具的 LLM 摘要逻辑（失败回退到启发式）。 |
| 沙箱 | `.env` (`SANDBOX_FUSION_ENDPOINTS`) | 控制 Python 工具的沙箱执行端点。 |
| MCP 服务 | `config/mcp.json`、`.env` (`MCP_CONFIG_PATH`)、`docs/mcp/` | 配置基于 FastMCP 的服务，将工具暴露给 MCP 客户端。 |

## 已实现的工具

- **`web_search`**（`tools/search_tool.py`）：Serper API 搜索，支持区域参数、重试与缓存。
- **`scholar_search`**（`tools/scholar_tool.py`）：基于 Serper 的 Google Scholar 查询，返回结构化信息（PDF 链接、引用次数等），可批量处理多个查询。
- **`python`**（`tools/python_tool.py`）：沙箱优先执行，带安全检测与本地兜底。
- **`web_visit`**（`tools/visit_tool.py`）：Jina Reader + BeautifulSoup 多 URL 抓取，支持 LLM 摘要与缓存。默认仅返回摘要结果（原始内容仍被缓存），需要原文时可在请求中添加 `return_raw_content=true`。

每个工具都提供 JSON Schema 用于验证/文档，新增工具的流程见 `tool_module_development.md`。

## 扩展指引

1. 实现工具 callable 及输入/输出 schema。
2. 使用 `ToolDefinition` 封装，并在工厂函数中处理依赖注入。
3. 通过 `ToolRegistry` 注册，并在 `tests/` 下添加覆盖。
4. 更新 `changelog.md` 与相关文档。

更多细节可参考 `tool_module_development.md` 及 `changelog.md`。

## 贡献

欢迎提交 Issue 或 PR。请在提交前：

- 执行 `python -m pytest`。
- 更新 `changelog.md` 与相应文档。
- 保持中英文文档同步。

如需讨论路线图或设计问题，请在 Issue 中注明涉及的模块或章节。

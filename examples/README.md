# Tool Registry + OpenAI Demo

## Prerequisites
- Install project requirements: `pip install -r requirements.txt`
- Export the following environment variables:
  - `OPENAI_API_KEY`: OpenAI API token
  - `OPENAI_BASE_URL` (optional): custom API endpoint when using compatible providers
  - `OPENAI_MODEL` (optional): Chat model to use (default `gpt-4o-mini`)
  - `SANDBOX_FUSION_ENDPOINTS` or `SANDBOX_FUSION_ENDPOINT` if the python tool should execute via sandbox

## Run
```bash
python examples/registry_openai_demo.py [--tools TOOL ...] [--export-history] [--output-dir PATH]
```

Enter natural language tasks when prompted. The assistant relies on prompt instructions (no built-in function calling). When the model emits a `<tool_call>` block, the script executes the requested tool, prints the result (including `backend`), and feeds it back via `<tool_response>` for continued reasoning.

### Tool selection
Use `--tools` to restrict which tool definitions are registered. The following identifiers are available:
- `python`
- `web_search`

Example: run only the Python tool.
```bash
python examples/registry_openai_demo.py --tools python
```

### Chat history export
- Pass `--export-history` to save the transcript when you exit (`exit`/`quit`).  
- Within an active session, type `export` or `output` to flush the history immediately.
- Files are written under `examples/outputs/<model>/chat-history-<timestamp>.json`.

### Optional caching
1. Copy `.env.template` to `.env`, then set `CACHE_ENABLED=true`.
2. Duplicate `config/cache.example.json` to `config/cache.json` (git-ignored) and tailor the `backend` section:
   - `backend: "sqlite"` (default) stores cache files under `.cache/`.
   - `backend: "mysql"` uses the `mysql` section; populate host, user, password, etc.
3. Adjust `CACHE_CONFIG_PATH` in `.env` if you keep the config elsewhere.
4. Optionally set `CACHE_BACKEND` in `.env` to override the backend specified in the config (`sqlite` or `mysql`).
5. When caching is enabled, the demo loads the config file and instantiates the selected backend automatically.

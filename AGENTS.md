@/Users/drnoobmaster/.codex/RTK.md

Use jCodeMunch MCP tools for code exploration whenever they can answer the question.
- Start with `resolve_repo`; if not indexed, call `index_folder`.
- Then prefer `plan_turn` or `get_repo_outline`.
- Prefer `search_symbols`, `get_context_bundle`, `get_file_outline`, `get_symbol_source`, and `search_text`.
- Use native reads or shell search only for edits, builds/tests, non-code assets, or when jCodeMunch cannot answer.

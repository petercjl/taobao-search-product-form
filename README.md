# Taobao search product-form research

This public npm package distributes the canonical `taobao-search-product-form` Agent Skill and its deterministic scripts. It accepts a user-supplied Taobao search-result workbook and creates local evidence and an HTML research report. Product-image interpretation and report rendering require capabilities supplied by the active Agent; the package does not provide a standalone image model.

The verified full-workflow host is Codex on macOS. SealSeek and Windows have an implemented installation adapter and automated package checks, but a complete image-analysis and HTML run is not yet verified there. The report stage depends on the separately installed `compact-commerce-ui` Skill/CLI. Python stages require Python 3 with the packages in `requirements.txt`; the CLI probes a managed environment and working platform interpreters, and `TAOBAO_SEARCH_PYTHON` can select a specific interpreter. `taobao-search-form doctor --json` checks imports and the report CLI. No platform account, marketplace credential, or npm token is included.

```sh
npm install -g @petercjl/taobao-search-product-form@latest
taobao-search-form doctor --json
taobao-search-form skill source --json
taobao-search-form skill status --agent codex
taobao-search-form skill install --agent codex
```

For SealSeek, use `taobao-search-form skill status --agent sealseek` and `taobao-search-form skill install --agent sealseek`. On Windows, this targets the user's SealSeek workspace Skill directory and defaults to a managed copy. Before each new analysis, run `taobao-search-form update check` and `taobao-search-form doctor --json`. A managed installation can update the npm package and synchronize its Skill in one command: `taobao-search-form update install --agent sealseek --yes` (or `--agent codex` on Codex). A custom managed Skill directory uses `--target-dir DIR`.

`skill install` refuses to replace an existing unmanaged Skill. If this machine already has a hand-maintained installation, retain it and migrate it deliberately after checking differences. `skill update` only replaces a copy installed by this CLI and first moves the previous copy to a recoverable backup. On macOS the default installation is a link to the npm package's canonical Skill.

The full report's evidence-table filter/sort experience remains under review. SealSeek image inspection and report rendering still require host validation; the package does not claim a completed SealSeek end-to-end regression. The Skill's evidence limits and output contract are documented in `skill/taobao-search-product-form/SKILL.md`.

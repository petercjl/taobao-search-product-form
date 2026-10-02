# Taobao search product-form research

This public npm package distributes the canonical `taobao-search-product-form` Agent Skill, deterministic scripts, and a pinned HTML report runtime. It accepts a user-supplied Taobao search-result workbook and creates local evidence and an HTML research report. Product-image interpretation requires an image-capable Agent; the package does not provide a standalone image model.

The verified full-workflow host is Codex on macOS. SealSeek and Windows have an implemented installation adapter and automated package checks, but a complete image-analysis and HTML run is not yet verified there. The report stage uses the renderer, validator and template bundled in this package; `compact-commerce-ui` is a development-time template-design tool only. Python stages require Python 3 with the packages in `requirements.txt`; the CLI checks SealSeek's managed Python environment, a package-managed environment, and working platform interpreters. `TAOBAO_SEARCH_PYTHON` can select a specific interpreter. `taobao-search-form doctor --json` checks imports and the bundled report runtime. No platform account, marketplace credential, or npm token is included.

```sh
npm install -g @petercjl/taobao-search-product-form@latest
taobao-search-form doctor --json
taobao-search-form skill source --json
taobao-search-form skill status --agent codex
taobao-search-form skill install --agent codex
```

For SealSeek, use `taobao-search-form skill status --agent sealseek` and `taobao-search-form skill install --agent sealseek`. On Windows, this targets the user's SealSeek workspace Skill directory and defaults to a managed copy. The first install creates SealSeek display metadata; later updates preserve customized display metadata. A managed update keeps a recoverable backup and can synchronize files in place when a running Agent locks the Skill directory. Locally edited managed files are reported as `modified` and are not overwritten automatically. Before each new analysis, run `taobao-search-form update check` and `taobao-search-form doctor --json`. A managed installation can update the npm package and synchronize its Skill in one command: `taobao-search-form update install --agent sealseek --yes` (or `--agent codex` on Codex). A custom managed Skill directory uses `--target-dir DIR`.

`skill install` refuses to replace an existing unmanaged Skill. If this machine already has a hand-maintained installation, retain it and migrate it deliberately after checking differences. `skill update` only replaces a copy installed by this CLI and first moves the previous copy to a recoverable backup. On macOS the default installation is a link to the npm package's canonical Skill.

The full report's evidence-table filter/sort experience remains under review. On SealSeek, one local image and one HTTPS image URL have been inspected successfully; a full per-product image-analysis and report run still requires host validation. Images are inspected individually and recorded by product ID and image hash; 10-product batches are resumable checkpoints, while contact sheets are for orientation and QA. The Skill's evidence limits and output contract are documented in `skill/taobao-search-product-form/SKILL.md`.

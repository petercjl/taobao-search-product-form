# Taobao search product-form research

This public npm package distributes the canonical `taobao-search-product-form` Agent Skill and its deterministic scripts. It accepts a user-supplied Taobao search-result workbook and creates local evidence and an HTML research report. Product-image interpretation and report rendering require capabilities supplied by the active Agent; the package does not provide a standalone image model.

The verified host is Codex on macOS. SealSeek and other operating systems are not yet verified. The report stage depends on the separately installed `compact-commerce-ui` Skill/CLI. Python stages require Python 3 with the packages in `requirements.txt`; install them into a stable user-managed Python environment and set `TAOBAO_SEARCH_PYTHON` to its interpreter. `taobao-search-form doctor --json` checks these imports. No platform account, marketplace credential, or npm token is included.

```sh
npm install -g @petercjl/taobao-search-product-form@next
taobao-search-form doctor --json
taobao-search-form skill source --json
taobao-search-form skill status --agent codex
taobao-search-form skill install --agent codex
```

`skill install` refuses to replace an existing unmanaged Skill. If this machine already has a hand-maintained installation, retain it and migrate it deliberately after checking differences. `skill update` only replaces a copy installed by this CLI and first moves the previous copy to a recoverable backup. On macOS the default installation is a link to the npm package's canonical Skill.

Package version `0.1.0-next.0` is a preview. The full report's evidence-table filter/sort experience remains under review; this preview does not claim a completed end-to-end regression. The Skill's evidence limits and output contract are documented in `skill/taobao-search-product-form/SKILL.md`.

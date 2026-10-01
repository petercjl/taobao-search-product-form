# Stage ledger

The per-run `ledger.json` lives beside that run's data, not inside this Skill. It records two independent dimensions: `design_state` (`open`, `defined`, `validated`) describes how mature the stage method is; `status` describes what happened in this particular run. A stage can have a defined method without having been executed, or a provisional result awaiting review.

The initial stages are `input`, `clean`, `classify`, `compare`, `decide`, and `report`. Add a classification module with a stage ID such as `classify/placement` or `classify/visual-form` when that module is selected. These IDs are navigation handles, not a declaration of the module's eventual field schema or algorithm.

Statuses:

- `not_started`: no current result.
- `in_progress`: work begun, with intermediate artifacts if any.
- `awaiting_review`: development result exists and awaits the user's review.
- `approved`: the user confirmed the development result; record reviewer and what was approved.
- `verified`: run-mode result passed its automatic QA.
- `blocked`: cannot safely advance; record the reason.
- `skipped`: reserved for a documented development-stage experiment outside the complete run; record why when it could be mistaken for missing work.

Commands (resolve the script relative to the Skill directory):

```text
python3 scripts/workflow_ledger.py init --run-dir RUN_DIR --mode development --input WORKBOOK
python3 scripts/workflow_ledger.py show --ledger RUN_DIR/ledger.json
python3 scripts/workflow_ledger.py record --ledger RUN_DIR/ledger.json --stage clean --status awaiting_review --artifact OUTPUT_FILE --note "What was checked and what remains for review"
python3 scripts/workflow_ledger.py record --ledger RUN_DIR/ledger.json --stage clean --status approved --reviewer USER --note "What the user confirmed"
```

`record` also accepts `--design-state`, `--strategy` and repeated `--artifact`. Artifact paths are resolved to existing files and stored with size and SHA-256 so later work can detect changed inputs or intermediates. Each update adds an event and creates a recoverable backup of the previous ledger. `init` refuses to replace an existing ledger.

In development mode, a stage may be reviewed and approved independently while the complete workflow is being built. The next stage reads its actual approved artifacts and ledger scope. Record parent and downstream stages when their artifacts are produced; approval of a report does not automatically approve each source stage. If an input or strategy change makes a downstream result stale, mark that downstream stage accordingly with a reason before reusing it. In run mode, execute every required stage and module, update the ledger after each material transition, and continue after automated verification without routine user review. A development-stage review may stop after its current module and hand off the ledger plus artifacts.

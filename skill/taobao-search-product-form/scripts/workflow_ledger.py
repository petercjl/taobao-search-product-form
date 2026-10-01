#!/usr/bin/env python3
"""Small, recoverable stage ledger for development and end-to-end runs."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


STAGES = ("input", "clean", "classify", "compare", "decide", "report")
STATUSES = ("not_started", "in_progress", "awaiting_review", "approved", "verified", "blocked", "skipped")
DESIGN_STATES = ("open", "defined", "validated")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_record():
    return {"design_state": "open", "status": "not_started", "strategy": None,
            "artifacts": [], "review": None, "note": None, "updated_at": None}


def artifact_intact(item):
    path = Path(item["path"])
    return path.is_file() and path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"]


def command_init(args):
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"input workbook not found: {source}")
    run_dir = Path(args.run_dir).expanduser().resolve()
    ledger = run_dir / "ledger.json"
    if ledger.exists() or ledger.is_symlink():
        raise FileExistsError(f"ledger already exists: {ledger}")
    run_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now()
    document = {
        "schema_version": 1,
        "mode": args.mode,
        "created_at": timestamp,
        "updated_at": timestamp,
        "input": {"path": str(source), "sha256": sha256(source), "bytes": source.stat().st_size},
        "stages": {name: stage_record() for name in STAGES},
        "events": [{"at": timestamp, "action": "init", "note": "Run ledger initialized; stages await design or execution."}],
    }
    with ledger.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"ledger": str(ledger), "mode": args.mode, "stages": list(STAGES)}, ensure_ascii=False))


def command_show(args):
    ledger = Path(args.ledger).expanduser().resolve()
    document = json.loads(ledger.read_text(encoding="utf-8"))
    input_path = Path(document["input"]["path"])
    input_intact = input_path.is_file() and sha256(input_path) == document["input"]["sha256"]
    result = {"ledger": str(ledger), "mode": document["mode"], "input": document["input"],
              "input_intact": input_intact,
              "stages": {key: {"design_state": value["design_state"], "status": value["status"],
                               "strategy": value["strategy"], "artifacts": value["artifacts"],
                               "artifacts_intact": all(artifact_intact(item) for item in value["artifacts"]),
                               "note": value["note"]} for key, value in document["stages"].items()}}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_record(args):
    ledger = Path(args.ledger).expanduser().resolve()
    if ledger.is_symlink() or not ledger.is_file():
        raise ValueError(f"ledger must be an existing regular file: {ledger}")
    document = json.loads(ledger.read_text(encoding="utf-8"))
    stage_id = args.stage
    if stage_id not in document["stages"]:
        if not stage_id.startswith("classify/") or len(stage_id) <= len("classify/"):
            raise ValueError(f"unknown stage: {stage_id}; use classify/NAME for a module")
        document["stages"][stage_id] = stage_record()
    stage = document["stages"][stage_id]
    if args.status == "approved" and (document["mode"] != "development" or not args.reviewer or not args.note):
        raise ValueError("approved requires development mode, --reviewer and --note recording confirmation")
    if args.status == "verified" and document["mode"] != "run":
        raise ValueError("verified is reserved for run-mode automated QA")
    if args.status == "awaiting_review" and document["mode"] != "development":
        raise ValueError("awaiting_review is reserved for development mode")
    if args.status == "blocked" and not args.note:
        raise ValueError("blocked requires --note")
    artifacts = []
    for raw in args.artifact:
        target = Path(raw).expanduser().resolve()
        if not target.is_file():
            raise ValueError(f"artifact does not exist as a file: {target}")
        artifacts.append({"path": str(target), "sha256": sha256(target), "bytes": target.stat().st_size})
    if args.status is not None:
        stage["status"] = args.status
    if args.design_state is not None:
        stage["design_state"] = args.design_state
    if args.strategy is not None:
        stage["strategy"] = args.strategy
    for artifact in artifacts:
        stage["artifacts"] = [old for old in stage["artifacts"] if old["path"] != artifact["path"]]
        stage["artifacts"].append(artifact)
    if args.note is not None:
        stage["note"] = args.note
    if args.status == "approved":
        stage["review"] = {"reviewer": args.reviewer, "at": now(), "note": args.note}
    elif args.status in ("not_started", "in_progress", "awaiting_review", "blocked"):
        stage["review"] = None
    timestamp = now()
    stage["updated_at"] = timestamp
    document["updated_at"] = timestamp
    document["events"].append({"at": timestamp, "action": "record", "stage": stage_id,
                               "status": stage["status"], "design_state": stage["design_state"],
                               "strategy": stage["strategy"], "artifacts_added": artifacts,
                               "note": args.note, "reviewer": args.reviewer})
    backup = ledger.with_name(ledger.name + ".bak-" + uuid.uuid4().hex[:12])
    shutil.copy2(ledger, backup)
    if not backup.is_file() or backup.stat().st_size == 0:
        raise OSError("ledger backup verification failed")
    fd, temporary = tempfile.mkstemp(prefix=".ledger-", suffix=".json", dir=ledger.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, ledger.stat().st_mode & 0o777)
        os.replace(temporary, ledger)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(json.dumps({"ledger": str(ledger), "backup": str(backup), "stage": stage_id,
                      "status": stage["status"], "artifacts": stage["artifacts"]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--run-dir", required=True)
    init.add_argument("--mode", choices=("development", "run"), required=True)
    init.add_argument("--input", required=True)
    init.set_defaults(func=command_init)
    show = commands.add_parser("show")
    show.add_argument("--ledger", required=True)
    show.set_defaults(func=command_show)
    record = commands.add_parser("record")
    record.add_argument("--ledger", required=True)
    record.add_argument("--stage", required=True)
    record.add_argument("--status", choices=STATUSES)
    record.add_argument("--design-state", choices=DESIGN_STATES)
    record.add_argument("--strategy")
    record.add_argument("--artifact", action="append", default=[])
    record.add_argument("--note")
    record.add_argument("--reviewer")
    record.set_defaults(func=command_record)
    args = parser.parse_args()
    try:
        args.func(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()

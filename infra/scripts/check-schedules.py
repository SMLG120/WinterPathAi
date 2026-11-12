#!/usr/bin/env python3
"""Fail if a workflow's cron strings and its jobs' `github.event.schedule == '...'` guards drift.

A cron that no job references, or a guard naming a cron that is not scheduled, makes a job be
silently SKIPPED on schedule (GitHub reports no error). Usage: check-schedules.py FILE.yml ...
Needs PyYAML (present in the tests/integration venv).
"""

from __future__ import annotations

import re
import sys

import yaml

GUARD = re.compile(r"github\.event\.schedule\s*==\s*'([^']+)'")


def check(path: str) -> list[str]:
    doc = yaml.safe_load(open(path, encoding="utf-8"))
    on = doc.get("on", doc.get(True, {})) or {}  # PyYAML may parse the key `on` as True
    crons = {c["cron"] for c in (on.get("schedule") or []) if isinstance(c, dict)}
    guards: dict[str, set[str]] = {}
    for name, job in (doc.get("jobs") or {}).items():
        for cron in GUARD.findall(str(job.get("if", ""))):
            guards.setdefault(cron, set()).add(name)
    problems = [
        f"{path}: cron '{c}' is not referenced by any job if: (jobs skip silently)"
        for c in sorted(crons - set(guards))
    ]
    problems += [
        f"{path}: job(s) {sorted(guards[g])} guard on '{g}', which is not in on.schedule"
        for g in sorted(set(guards) - crons)
    ]
    if not problems:
        print(f"{path}: {len(crons)} cron(s), every one guarded, no dangling guards")
    return problems


if __name__ == "__main__":
    errs = [p for f in sys.argv[1:] for p in check(f)]
    for e in errs:
        print(f"ERROR {e}", file=sys.stderr)
    sys.exit(1 if errs else 0)

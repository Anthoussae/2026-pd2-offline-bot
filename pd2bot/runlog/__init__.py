"""Remembering what happened: the run event log and the narrative log.

events.py writes/reads the per-run events.jsonl (always on, schema in
docs/architecture/run-log.md); narrate.py writes the human story. When a
run misbehaves, read the log first - do not reason from silence.
"""

from pd2bot.runlog.events import (
    SCHEMA_VERSION,
    NullRunLog,
    RunLog,
    describe_event,
    latest_run,
    load,
    main,
    pickup_report,
    render,
    summarize,
)

__all__ = [
    "SCHEMA_VERSION",
    "NullRunLog",
    "RunLog",
    "describe_event",
    "latest_run",
    "load",
    "main",
    "pickup_report",
    "render",
    "summarize",
]

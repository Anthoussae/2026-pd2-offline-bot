# runlog/ — remembering what happened

| file | one job |
|---|---|
| events.py | the per-run events.jsonl: schema'd, append-only, always on; the reader/renderer CLI (`python -m pd2bot.runlog`) |
| narrate.py | the narrative log: one wall-clock line per meaningful act |

House rule: when a run misbehaves, read the event log FIRST — do not
reason from silence. Doc: docs/architecture/run-log.md

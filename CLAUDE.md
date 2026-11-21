# handover-brief

Turns a team chat export (JSON, see `docs/schema.md`) into a handover brief
(English, French and Arabic cues):
deadlines with their change history, decisions in force, open questions,
cancellations, unagreed proposals and owners, each linked to its source
messages. Deterministic rules, no LLM, standard library only.

## Run and test

- `python -m venv .venv`, then `pip install -e ".[dev]"`
- `handover serve` (port 8102), `handover build <thread.json> --out brief.html`,
  `handover bench`, `handover items <thread.json>`
- `python -m handover ...` is the same CLI (use it where Windows Application
  Control blocks the generated `handover.exe`)
- `pytest -q`

## Layout

- `handover/dates.py` resolves date phrases against the message's own date
- `handover/extract.py` cue patterns (`describe`) and the one-pass state machine (`Extractor.apply`), then unanswered questions
- `handover/bench.py` scoring rules from `docs/labelling.md`
- `handover/render.py` + `handover/static/brief.html` the single-file page (vanilla JS, data embedded as JSON)
- `handover/server.py` index and `/brief/<thread>`
- `data/threads`, `data/gold`, `data/splits.json` (tune: warehouse-golive, emergency-ops; held-out: rent-renewals)

## Quirks

- The held-out thread was measured once (`docs/heldout-first-run.txt`).
  Changing `extract.py` or `dates.py` means the held-out numbers in the
  README are no longer an unseen measurement: say so if you change them.
- Labels in the brief are quoted source sentences, never paraphrases.
- Screenshots in `docs/` come from the shared shot tool against `handover serve`.

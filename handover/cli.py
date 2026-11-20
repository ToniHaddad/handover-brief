"""Command line: handover build | serve | bench | items."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .model import ThreadError, load_thread

DATA = Path(__file__).resolve().parent.parent / "data"


def _data_dir(arg: str | None) -> Path:
    path = Path(arg) if arg else DATA
    if not (path / "threads").is_dir():
        sys.exit(f"no threads folder in {path}; pass --data")
    return path


def cmd_build(args) -> None:
    from .render import render_page
    try:
        thread = load_thread(args.thread)
    except (OSError, ThreadError, json.JSONDecodeError) as exc:
        sys.exit(f"cannot read {args.thread}: {exc}")
    html = render_page(thread)
    Path(args.out).write_text(html, encoding="utf-8")
    from .extract import extract
    items = extract(thread)
    counts = {}
    for i in items:
        counts[i.type] = counts.get(i.type, 0) + 1
    summary = ", ".join(f"{n} {t}" for t, n in sorted(counts.items()))
    print(f"{len(thread.messages)} messages -> {len(items)} items ({summary})")
    print(f"wrote {args.out} ({len(html) // 1024} KB, self-contained)")


def cmd_items(args) -> None:
    from .extract import extract
    thread = load_thread(args.thread)
    for i in extract(thread):
        when = i.date.isoformat() if i.date else ""
        who = i.owner or ""
        print(f"{i.type:<12} {i.status:<11} {i.origin_id:<6} {when:<10} {who:<18} {i.label[:70]}")


def cmd_serve(args) -> None:
    from .server import serve
    serve(_data_dir(args.data), args.port)


def cmd_bench(args) -> None:
    from .bench import run
    print(run(_data_dir(args.data), verbose=args.verbose, only=args.split))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="handover", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write a single self-contained HTML brief for one thread")
    b.add_argument("thread", help="thread JSON (docs/schema.md)")
    b.add_argument("--out", default="brief.html")
    b.set_defaults(func=cmd_build)

    i = sub.add_parser("items", help="print the extracted items as a table")
    i.add_argument("thread")
    i.set_defaults(func=cmd_items)

    s = sub.add_parser("serve", help="serve the briefs for every thread in the data folder")
    s.add_argument("--port", type=int, default=8102)
    s.add_argument("--data", help="folder with threads/ (default: the bundled data)")
    s.set_defaults(func=cmd_serve)

    m = sub.add_parser("bench", help="precision and recall against the gold labels")
    m.add_argument("--data", help="folder with threads/, gold/ and splits.json")
    m.add_argument("--split", choices=["tune", "heldout"], help="only one split")
    m.add_argument("-v", "--verbose", action="store_true", help="list every miss and extra")
    m.set_defaults(func=cmd_bench)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

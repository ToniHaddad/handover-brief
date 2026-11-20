"""A small local server: an index of threads and one brief per thread. Standard library only."""
from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .extract import extract
from .model import ThreadError, load_thread
from .render import render_page

INDEX = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Handover briefs</title>
<style>
:root{--paper:#f5f2ec;--card:#fffdf9;--ink:#1c2230;--ink-2:#4a5263;--ink-3:#7a8191;--rule:#e2dccf;--accent:#0e6b6b;
--moved:#a8641a;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--paper:#14171d;--card:#1b1f27;--ink:#e8e4dc;--ink-2:#b7b3ab;--ink-3:#8a8780;
--rule:#2b303a;--accent:#5cc2bb;--moved:#e2a75a;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:40px 16px}
.kicker{font:600 11px/1 "Segoe UI",system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
h1{font:600 30px/1.15 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;margin:8px 0 6px}
p{color:var(--ink-2);margin:0 0 24px}
a.t{display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--rule);border-left:4px solid var(--accent);
border-radius:10px;padding:14px 16px;margin-bottom:10px}
a.t:hover{border-color:var(--accent)}
.n{font:600 18px/1.3 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}.m{font-size:13px;color:var(--ink-3)}
.c{font-size:13px;color:var(--ink-2);margin-top:4px}.c b{color:var(--moved)}
</style></head><body><main><div class="kicker">Handover brief</div><h1>Team threads</h1>
<p>Synthetic chats from Northbridge Relief project teams. Open one to see its handover timeline.</p>
__LIST__</main></body></html>"""


def _summary(path: Path) -> tuple[str, str, str]:
    thread = load_thread(path)
    items = extract(thread)
    dl = sum(1 for i in items if i.type == "deadline" and i.status == "current")
    ch = sum(1 for i in items if i.changed and i.status != "cancelled")
    q = sum(1 for i in items if i.type == "question")
    meta = f"{thread.team} · {len(thread.messages)} messages"
    counts = f"{dl} current deadlines · <b>{ch} things changed</b> · {q} open questions"
    return thread.channel or path.stem, meta, counts


def make_handler(data_dir: Path):
    threads = data_dir / "threads"

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?")[0].split("#")[0]
            if path in ("/", "/index.html"):
                rows = []
                for f in sorted(threads.glob("*.json")):
                    name, meta, counts = _summary(f)
                    rows.append(f'<a class="t" href="/brief/{html.escape(f.stem)}"><div class="n">{html.escape(name)}</div>'
                                f'<div class="m">{html.escape(meta)}</div><div class="c">{counts}</div></a>')
                return self._send(200, INDEX.replace("__LIST__", "\n".join(rows)))
            if path.startswith("/brief/"):
                stem = path[len("/brief/"):].removesuffix(".html")
                f = threads / f"{stem}.json"
                if stem.replace("-", "").replace("_", "").isalnum() and f.is_file():
                    try:
                        return self._send(200, render_page(load_thread(f)))
                    except ThreadError as exc:
                        return self._send(500, f"bad thread file: {html.escape(str(exc))}", "text/plain; charset=utf-8")
            self._send(404, "not found", "text/plain; charset=utf-8")

        def log_message(self, fmt, *args) -> None:
            pass

    return Handler


def serve(data_dir: Path, port: int = 8102) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(data_dir))
    print(f"Serving {len(list((data_dir / 'threads').glob('*.json')))} threads on http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

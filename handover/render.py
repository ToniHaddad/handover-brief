"""Render a thread and its extracted items as one self-contained HTML page."""
from __future__ import annotations

import html
import json
from importlib import resources

from .dates import find_dates
from .extract import extract
from .model import Thread


def _segments(text: str, base) -> list[dict]:
    """Split message text into plain runs and resolved date mentions."""
    out, pos = [], 0
    for d in find_dates(text, base):
        if d.start > pos:
            out.append({"t": text[pos:d.start]})
        out.append({"t": d.text, "d": d.value.isoformat(), "past": d.kind == "past"})
        pos = d.end
    if pos < len(text):
        out.append({"t": text[pos:]})
    return out


def page_data(thread: Thread) -> dict:
    items = extract(thread)
    messages = [{
        "id": m.id,
        "idx": m.idx,
        "author": m.author,
        "ts": m.ts.isoformat(),
        "reply_to": m.reply_to,
        "edited": m.edited,
        "seg": _segments(m.text, m.day),
    } for m in thread.messages]
    return {
        "team": thread.team,
        "channel": thread.channel,
        "synthetic": thread.synthetic,
        "as_of": thread.messages[-1].day.isoformat() if thread.messages else None,
        "messages": messages,
        "items": [i.to_dict() for i in items],
    }


def render_page(thread: Thread) -> str:
    template = resources.files("handover").joinpath("static/brief.html").read_text(encoding="utf-8")
    data = json.dumps(page_data(thread), ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(f"{thread.channel or 'Handover'}: handover brief")
    return template.replace("__TITLE__", title).replace("__DATA__", data)

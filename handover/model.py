"""Data types shared by the loader, the extractor, the renderer and the benchmark."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass
class Message:
    id: str
    idx: int  # 1-based position in the thread
    author: str
    ts: datetime
    text: str
    reply_to: str | None = None
    edited: bool = False

    @property
    def day(self) -> date:
        """Local calendar date of the message (the offset in the timestamp is kept)."""
        return self.ts.date()


@dataclass
class Thread:
    team: str
    channel: str
    synthetic: bool
    messages: list[Message]

    def by_id(self) -> dict[str, Message]:
        return {m.id: m for m in self.messages}


@dataclass
class Version:
    """One step in an item's history: who set which value, in which message."""
    kind: str  # set | proposed | agreed | moved | corrected | rejected | cancelled | reversed | reassigned | mentioned
    message_id: str
    author: str
    value: str = ""
    note: str = ""


@dataclass
class Item:
    id: str
    type: str  # deadline | decision | proposal | owner | question | cancellation
    status: str  # current | cancelled | in_force | reversed | not_agreed | superseded | unanswered
    label: str
    origin_id: str
    source_ids: list[str] = field(default_factory=list)
    history: list[Version] = field(default_factory=list)
    date: date | None = None
    owner: str | None = None
    target: str | None = None  # cancellation: id of the cancelled item; decision: id of the replacing item
    keywords: set[str] = field(default_factory=set, repr=False)

    def add_source(self, message_id: str) -> None:
        if message_id not in self.source_ids:
            self.source_ids.append(message_id)

    @property
    def changed(self) -> bool:
        if self.type == "deadline":
            return len({v.value for v in self.history if v.kind in ("set", "moved", "corrected", "agreed")}) > 1
        return self.status in ("reversed", "superseded")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "label": self.label,
            "origin_id": self.origin_id,
            "source_ids": self.source_ids,
            "date": self.date.isoformat() if self.date else None,
            "owner": self.owner,
            "target": self.target,
            "changed": self.changed,
            "history": [v.__dict__ for v in self.history],
        }


class ThreadError(ValueError):
    pass


def load_thread(source: str | Path | dict) -> Thread:
    """Read a handover-thread/1 JSON file (see docs/schema.md) and validate it."""
    if isinstance(source, dict):
        raw = source
    else:
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("messages"), list):
        raise ThreadError("a thread is an object with a 'messages' list")
    messages: list[Message] = []
    seen: set[str] = set()
    for i, m in enumerate(raw["messages"], start=1):
        for key in ("id", "createdDateTime", "from", "body"):
            if key not in m:
                raise ThreadError(f"message {i} has no '{key}'")
        mid = str(m["id"])
        if mid in seen:
            raise ThreadError(f"duplicate message id {mid}")
        reply = m.get("replyToId")
        if reply is not None and str(reply) not in seen:
            raise ThreadError(f"message {mid} replies to unknown or later message {reply}")
        try:
            ts = datetime.fromisoformat(str(m["createdDateTime"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ThreadError(f"message {mid}: bad createdDateTime") from exc
        if messages and ts < messages[-1].ts:
            raise ThreadError(f"message {mid} is earlier than the message before it")
        seen.add(mid)
        messages.append(Message(mid, i, str(m["from"]), ts, str(m["body"]),
                                str(reply) if reply is not None else None, bool(m.get("edited", False))))
    return Thread(raw.get("team", ""), raw.get("channel", ""), bool(raw.get("synthetic", False)), messages)

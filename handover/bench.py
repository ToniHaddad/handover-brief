"""Score the extractor against gold labels (rules in docs/labelling.md)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .extract import extract
from .model import Item, load_thread

TYPES = ["deadline", "decision", "proposal", "owner", "question", "cancellation", "change"]
# Gold statuses that must never appear in a "current" section of the brief.
NOT_CURRENT = {"cancelled", "reversed", "superseded"}


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    misses: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)

    def add(self, other: "Score") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn
        self.misses += other.misses
        self.extras += other.extras

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None


@dataclass
class Stale:
    """Items the brief shows as current although gold says they are not."""
    shown: list[str] = field(default_factory=list)
    traps: int = 0  # gold items that are superseded, cancelled, reversed or never agreed
    hidden: list[str] = field(default_factory=list)  # the reverse error: current items shown as cancelled
    live: int = 0  # gold deadlines, decisions and owners that are current

    def add(self, other: "Stale") -> None:
        self.shown += other.shown
        self.traps += other.traps
        self.hidden += other.hidden
        self.live += other.live


def _attr_ok(pred: Item, gold: dict) -> bool:
    t = gold["type"]
    if t == "deadline":
        return (pred.date is not None and pred.date.isoformat() == gold["chain"][-1]
                and pred.status == gold.get("status", "current"))
    if t == "decision":
        return pred.status == gold["status"]
    if t == "owner":
        return pred.owner == gold["owner"] and pred.status == gold.get("status", "current")
    return True


def _pred_chain(item: Item) -> list[str]:
    chain: list[str] = []
    for v in item.history:
        if v.kind in ("set", "moved", "corrected") and v.value and (not chain or chain[-1] != v.value):
            chain.append(v.value)
    return chain


def score_thread(items: list[Item], gold_items: list[dict]) -> tuple[dict[str, Score], Stale]:
    scores = {t: Score() for t in TYPES}
    for t in TYPES[:-1]:
        preds = [i for i in items if i.type == t]
        golds = [g for g in gold_items if g["type"] == t]
        used: set[int] = set()
        for p in preds:
            hit = next((k for k, g in enumerate(golds)
                        if k not in used and p.origin_id in g["match_ids"] and _attr_ok(p, g)), None)
            if hit is None:
                scores[t].fp += 1
                scores[t].extras.append(f"{p.origin_id} {p.label}")
            else:
                used.add(hit)
                scores[t].tp += 1
        for k, g in enumerate(golds):
            if k not in used:
                scores[t].fn += 1
                scores[t].misses.append(f"{g['match_ids'][0]} {g['label']}")

    # changes: moved or corrected deadlines, reversed decisions, superseded owners
    def gold_changed(g):
        return (g["type"] == "deadline" and len(g["chain"]) > 1) or g.get("status") in ("reversed", "superseded")

    gold_changes = [g for g in gold_items if gold_changed(g)]
    pred_changes = [i for i in items if i.type in ("deadline", "decision", "owner") and i.changed]
    used = set()
    for p in pred_changes:
        hit = None
        for k, g in enumerate(gold_changes):
            if k in used or g["type"] != p.type or p.origin_id not in g["match_ids"]:
                continue
            if g["type"] == "deadline" and _pred_chain(p) != g["chain"]:
                continue
            if g["type"] != "deadline" and p.status != g["status"]:
                continue
            hit = k
            break
        if hit is None:
            scores["change"].fp += 1
            scores["change"].extras.append(f"{p.origin_id} {p.label} {_pred_chain(p) or p.status}")
        else:
            used.add(hit)
            scores["change"].tp += 1
    for k, g in enumerate(gold_changes):
        if k not in used:
            scores["change"].fn += 1
            scores["change"].misses.append(f"{g['match_ids'][0]} {g['label']} {g.get('chain') or g['status']}")

    # the number that matters: stale or unagreed items presented as current
    stale = Stale()
    stale.traps = sum(1 for g in gold_items
                      if g.get("status") in NOT_CURRENT or g["type"] == "proposal"
                      or (g["type"] == "deadline" and len(g["chain"]) > 1))
    shown = [i for i in items if (i.type == "deadline" and i.status == "current")
             or (i.type == "decision" and i.status == "in_force")
             or (i.type == "owner" and i.status == "current")]
    for p in shown:
        for g in gold_items:
            if p.origin_id not in g["match_ids"]:
                continue
            wrong = False
            if g["type"] == p.type and g.get("status") in NOT_CURRENT:
                wrong = True
            elif g["type"] == "proposal" and p.type == "decision":
                wrong = True
            elif g["type"] == "deadline" == p.type and p.date and p.date.isoformat() in g["chain"][:-1]:
                wrong = True
            if wrong:
                stale.shown.append(f"{p.origin_id} {p.type} '{p.label}' shown as current")
                break
    # the reverse error: something still on that the brief files as cancelled, reversed or handed over
    live = [g for g in gold_items if g["type"] in ("deadline", "decision", "owner")
            and g.get("status") in ("current", "in_force")]
    stale.live = len(live)
    for p in items:
        if p.type not in ("deadline", "decision", "owner") or p.status in ("current", "in_force"):
            continue
        if any(g["type"] == p.type and p.origin_id in g["match_ids"] for g in live):
            stale.hidden.append(f"{p.origin_id} {p.type} '{p.label}' shown as {p.status}")
    return scores, stale


def _fmt(x: float | None) -> str:
    return "  n/a" if x is None else f"{x:5.2f}"


def run(data_dir: Path, verbose: bool = False, only: str | None = None) -> str:
    splits = json.loads((data_dir / "splits.json").read_text(encoding="utf-8"))
    lines: list[str] = []
    for split in ("tune", "heldout"):
        if only and split != only:
            continue
        totals = {t: Score() for t in TYPES}
        stale_total = Stale()
        names = splits[split]
        for name in names:
            thread = load_thread(data_dir / "threads" / f"{name}.json")
            gold = json.loads((data_dir / "gold" / f"{name}.gold.json").read_text(encoding="utf-8"))
            scores, stale = score_thread(extract(thread), gold["items"])
            for t in TYPES:
                totals[t].add(scores[t])
            stale_total.add(stale)
        lines.append(f"== {split} ({', '.join(names)}) ==")
        lines.append(f"{'type':<13} {'gold':>4} {'found':>5} {'right':>5}  precision  recall")
        for t in TYPES:
            s = totals[t]
            lines.append(f"{t:<13} {s.tp + s.fn:>4} {s.tp + s.fp:>5} {s.tp:>5}      {_fmt(s.precision)}   {_fmt(s.recall)}")
        all_tp = sum(totals[t].tp for t in TYPES[:-1])
        all_fp = sum(totals[t].fp for t in TYPES[:-1])
        all_fn = sum(totals[t].fn for t in TYPES[:-1])
        lines.append(f"{'all items':<13} {all_tp + all_fn:>4} {all_tp + all_fp:>5} {all_tp:>5}      "
                     f"{_fmt(all_tp / (all_tp + all_fp))}   {_fmt(all_tp / (all_tp + all_fn))}")
        lines.append(f"Superseded, cancelled or unagreed items shown as current: "
                     f"{len(stale_total.shown)} (out of {stale_total.traps} such items in gold)")
        for s in stale_total.shown:
            lines.append(f"  ! {s}")
        lines.append(f"Current items shown as cancelled, reversed or handed over: "
                     f"{len(stale_total.hidden)} (out of {stale_total.live} current items in gold)")
        for s in stale_total.hidden:
            lines.append(f"  ! {s}")
        if verbose:
            for t in TYPES:
                for m in totals[t].misses:
                    lines.append(f"  missed {t}: {m}")
                for e in totals[t].extras:
                    lines.append(f"  extra  {t}: {e}")
        lines.append("")
    return "\n".join(lines)

"""Loader validation, benchmark scoring, the rendered page and the local server."""
import json
import threading
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from handover.bench import score_thread
from handover.model import Item, ThreadError, Version, load_thread
from handover.render import render_page
from handover.server import make_handler

DATA = Path(__file__).resolve().parent.parent / "data"


def msg(mid, text="hi", when="2026-03-02T09:00:00+02:00", reply=None):
    return {"id": mid, "createdDateTime": when, "from": "Amal Rizk", "body": text, "replyToId": reply}


def test_loader_reads_all_bundled_threads():
    for f in (DATA / "threads").glob("*.json"):
        t = load_thread(f)
        assert 60 <= len(t.messages) <= 120 and t.synthetic


@pytest.mark.parametrize("messages,error", [
    ([msg("1"), msg("1")], "duplicate"),
    ([msg("1", reply="9")], "unknown"),
    ([{"id": "1", "from": "A", "body": "x"}], "createdDateTime"),
    ([msg("1", when="2026-03-02T09:00:00+02:00"), msg("2", when="2026-03-01T09:00:00+02:00")], "earlier"),
])
def test_loader_rejects_bad_threads(messages, error):
    with pytest.raises(ThreadError, match=error):
        load_thread({"messages": messages})


def test_gold_labels_point_at_real_messages():
    for f in (DATA / "gold").glob("*.gold.json"):
        gold = json.loads(f.read_text(encoding="utf-8"))
        ids = {m.id for m in load_thread(DATA / "threads" / f"{gold['thread']}.json").messages}
        for item in gold["items"]:
            assert set(item["match_ids"]) <= ids, item


def test_score_counts_stale_deadline_shown_as_current():
    gold = [{"type": "deadline", "label": "x", "match_ids": ["1"], "chain": ["2026-03-06", "2026-03-09"], "status": "current"}]
    stale_pred = Item("deadline-1", "deadline", "current", "x", "1", ["1"],
                      [Version("set", "1", "A", "2026-03-06")], date=date(2026, 3, 6))
    scores, stale = score_thread([stale_pred], gold)
    assert scores["deadline"].tp == 0 and scores["deadline"].fn == 1
    assert len(stale.shown) == 1 and stale.traps == 1


def test_score_counts_unagreed_proposal_shown_as_decision():
    gold = [{"type": "proposal", "label": "x", "match_ids": ["5"]}]
    pred = Item("decision-1", "decision", "in_force", "x", "5", ["5"])
    _, stale = score_thread([pred], gold)
    assert len(stale.shown) == 1


def test_rendered_page_is_self_contained():
    page = render_page(load_thread(DATA / "threads" / "warehouse-golive.json"))
    assert "<script src" not in page and "<link" not in page and "http://" not in page.split("<script id=\"data\"")[0]
    data = json.loads(page.split('type="application/json">')[1].split("</script>")[0])
    assert any(i["type"] == "deadline" and i["changed"] for i in data["items"])
    # dates inside messages are resolved for the reader
    assert any(s.get("d") for m in data["messages"] for s in m["seg"])


def test_server_serves_index_and_briefs():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(DATA))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        index = urllib.request.urlopen(base + "/").read().decode()
        assert "WH-14 go-live" in index
        brief = urllib.request.urlopen(base + "/brief/warehouse-golive").read().decode()
        assert "Handover brief" in brief
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/brief/..%2Fsplits")
    finally:
        server.shutdown()

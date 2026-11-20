"""Behaviour of the extraction rules on small hand-written threads."""
from datetime import date

from handover.extract import extract
from handover.model import load_thread


def thread(*rows):
    """rows: (id, 'YYYY-MM-DD HH:MM', author, text) or with a fifth reply-to id."""
    msgs = []
    for row in rows:
        mid, when, author, text, *reply = row
        msgs.append({"id": mid, "createdDateTime": when.replace(" ", "T") + ":00+02:00",
                     "from": author, "body": text, "replyToId": reply[0] if reply else None})
    return extract(load_thread({"messages": msgs}))


def of(items, type_):
    return [i for i in items if i.type == type_]


# 2026-03-03 is a Tuesday.

def test_deadline_moved_twice_keeps_the_whole_chain():
    items = thread(
        ("1", "2026-03-03 09:40", "Amal Rizk", "Atlas say racking installation done by Friday."),
        ("2", "2026-03-05 08:30", "Karim Nassar", "Bad news: steel delivery is late. Racking pushed to Monday."),
        ("3", "2026-03-09 08:10", "Amal Rizk", "Atlas are short a crew. Racking now Wednesday the 11th."),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 3, 11)
    assert [v.value for v in d.history if v.kind in ("set", "moved")] == ["2026-03-06", "2026-03-09", "2026-03-11"]
    assert [v.message_id for v in d.history if v.kind == "moved"] == ["2", "3"]
    assert [v.author for v in d.history if v.kind == "moved"] == ["Karim Nassar", "Amal Rizk"]
    assert d.changed


def test_correction_by_the_author_replaces_the_date():
    items = thread(
        ("1", "2026-03-04 09:02", "Amal Rizk", "Main move day is the 17th."),
        ("2", "2026-03-04 09:06", "Amal Rizk", "sorry, I meant the 18th. The 17th is the staff retreat.", "1"),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 3, 18)
    assert d.history[-1].kind == "corrected"


def test_move_that_nobody_agreed_to_does_not_change_the_deadline():
    items = thread(
        ("1", "2026-03-04 09:02", "Amal Rizk", "Main move day is Wednesday 18 March."),
        ("2", "2026-03-12 09:30", "Karim Nassar", "Could we push move day to Friday the 20th? Drivers prefer it."),
        ("3", "2026-03-12 09:41", "Amal Rizk", "No, the 18th stays. The trucks are booked.", "2"),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 3, 18)
    [p] = of(items, "proposal")
    assert p.origin_id == "2" and p.status == "not_agreed"
    assert not of(items, "decision")


def test_agreed_move_changes_the_deadline_and_records_who_agreed():
    items = thread(
        ("1", "2026-05-04 08:30", "Wanjiru Kamau", "Distribution date is 14 May."),
        ("2", "2026-05-13 09:00", "Wanjiru Kamau", "Can we move distribution to Thursday 21st?"),
        ("3", "2026-05-13 09:10", "Otieno Ouma", "Agreed, 21st.", "2"),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 5, 21)
    assert ("agreed", "3", "Otieno Ouma") in [(v.kind, v.message_id, v.author) for v in d.history]
    assert not of(items, "proposal")


def test_proposal_without_agreement_is_never_a_decision():
    items = thread(
        ("1", "2026-05-07 09:00", "Achieng Odhiambo", "Should we pay the first 100 households early as a test?"),
        ("2", "2026-05-07 09:05", "Ekai Lokwang", "finally some rain here"),
        ("3", "2026-05-08 09:00", "Wanjiru Kamau", "Final list is with the provider."),
    )
    assert not of(items, "decision")
    [p] = of(items, "proposal")
    assert p.status == "not_agreed"


def test_agreement_must_come_from_another_person():
    items = thread(
        ("1", "2026-03-05 09:12", "Rana Khoury", "Let's go with Bekaa Freight for the move."),
        ("2", "2026-03-05 09:13", "Rana Khoury", "ok"),
    )
    assert not of(items, "decision")
    assert len(of(items, "proposal")) == 1


def test_proposal_agreed_by_another_person_is_a_decision():
    items = thread(
        ("1", "2026-03-05 09:12", "Rana Khoury", "Let's go with Bekaa Freight for the move."),
        ("2", "2026-03-05 09:20", "Amal Rizk", "Agreed, go with Bekaa.", "1"),
    )
    [d] = of(items, "decision")
    assert d.status == "in_force" and d.source_ids == ["1", "2"]


def test_hedged_reply_is_not_agreement():
    items = thread(
        ("1", "2026-03-05 09:40", "Daniel Mensah", "What if we do a Saturday shift to move slow stock early?"),
        ("2", "2026-03-05 09:52", "Marc Aoun", "Possibly. I need to check the overtime rules.", "1"),
    )
    assert not of(items, "decision")
    assert len(of(items, "proposal")) == 1


def test_later_decision_reverses_the_earlier_one():
    items = thread(
        ("1", "2026-03-05 09:12", "Rana Khoury", "Bekaa Freight is cheapest. Let's go with Bekaa Freight."),
        ("2", "2026-03-05 09:20", "Amal Rizk", "Agreed.", "1"),
        ("3", "2026-03-12 09:00", "Rana Khoury", "Bekaa Freight can't do our date. Let's switch to Cedar Line instead."),
        ("4", "2026-03-12 09:10", "Amal Rizk", "Yes, switch.", "3"),
    )
    old, new = of(items, "decision")
    assert old.status == "reversed" and old.target == new.id
    assert new.status == "in_force"


def test_announced_decision_counts_without_a_reply():
    items = thread(
        ("1", "2026-03-10 09:00", "Marc Aoun", "Decision from the CD: cold-chain items go to Beirut, not Chtaura."),
    )
    [d] = of(items, "decision")
    assert d.status == "in_force"


def test_cancellation_marks_the_dated_event_cancelled():
    items = thread(
        ("1", "2026-03-04 11:41", "Amal Rizk", "Site visit with the donor advisor on 12 March, 10:00 at Chtaura."),
        ("2", "2026-03-11 11:15", "Joelle Saba", "The advisor is stuck in Beirut. Thursday's site visit is off."),
        ("3", "2026-03-11 11:20", "Amal Rizk", "Ok. Cancelling the room booking.", "2"),
    )
    [d] = of(items, "deadline")
    assert d.status == "cancelled"
    [c] = of(items, "cancellation")
    assert c.target == d.id and c.source_ids == ["2", "3"]


def test_cancelled_task_takes_its_owner_with_it():
    items = thread(
        ("1", "2026-03-06 10:05", "Rana Khoury", "Our label printer is dead. Leave it with me, I'll order a new one."),
        ("2", "2026-03-16 10:00", "Rana Khoury", "We don't need the label printer after all. Dropping that task.", "1"),
    )
    [o] = of(items, "owner")
    assert o.status == "cancelled"


def test_cancelling_one_thing_leaves_what_is_still_on():
    items = thread(
        ("1", "2026-03-19 09:00", "Amal Rizk", "Furniture leaves Zahle next Monday with the cleaning crew."),
        ("2", "2026-03-20 08:45", "Marc Aoun", "The cleaning crew is cancelled. Furniture still goes next Monday."),
    )
    [d] = of(items, "deadline")
    assert d.status == "current"


def test_claimed_task_and_accepted_request_make_owners():
    items = thread(
        ("1", "2026-03-02 10:17", "Daniel Mensah", "I'll take the stock count."),
        ("2", "2026-03-02 10:20", "Amal Rizk", "@Rana can you get freight quotes?"),
        ("3", "2026-03-02 10:34", "Rana Khoury", "Sure, will have them by Thursday.", "2"),
        ("4", "2026-03-02 10:40", "Amal Rizk", "@Karim can you book the forklift?"),
    )
    owners = {o.owner: o for o in of(items, "owner")}
    assert set(owners) == {"Daniel Mensah", "Rana Khoury"}  # Karim never accepted
    assert owners["Rana Khoury"].origin_id == "2"
    [d] = of(items, "deadline")
    assert d.date == date(2026, 3, 5)


def test_takeover_supersedes_the_previous_owner():
    items = thread(
        ("1", "2026-03-02 10:17", "Daniel Mensah", "I'll take the stock count."),
        ("2", "2026-03-13 08:20", "Amal Rizk", "@Rana can you take over the stock count?"),
        ("3", "2026-03-13 08:35", "Rana Khoury", "Yes, I'll take it over.", "2"),
    )
    daniel, rana = of(items, "owner")
    assert daniel.status == "superseded" and rana.status == "current"


def test_unanswered_question_is_listed_and_answered_one_is_not():
    items = thread(
        ("1", "2026-03-09 10:00", "Rana Khoury", "Who has the keys to the back gate at the old site?"),
        ("2", "2026-03-09 10:02", "Karim Nassar", "anyone going to the market at lunch? need batteries"),
        ("3", "2026-03-10 09:00", "Joelle Saba", "Is the forklift included in the quote?"),
        ("4", "2026-03-10 09:05", "Amal Rizk", "No, it's separate.", "3"),
        ("5", "2026-03-10 09:30", "Rana Khoury", "Has the landlord seen the floor plan?"),
        ("6", "2026-03-10 09:40", "Amal Rizk", "Yes, he signed it off."),
    )
    qs = of(items, "question")
    assert [q.origin_id for q in qs] == ["1"]  # lunch chatter is not a handover question


def test_question_answered_only_by_side_chatter_stays_open():
    items = thread(
        ("1", "2026-05-18 08:30", "Wanjiru Kamau", "Has the provider confirmed the float is loaded?"),
        ("2", "2026-05-18 08:45", "Achieng Odhiambo", "Working from home today, my son has a fever."),
        ("3", "2026-05-18 09:30", "Achieng Odhiambo", "Budget revision done and sent to Tom."),
    )
    assert [q.origin_id for q in of(items, "question")] == ["1"]


def test_every_item_points_at_real_messages():
    items = thread(
        ("1", "2026-03-03 09:40", "Amal Rizk", "Racking done by Friday."),
        ("2", "2026-03-05 08:30", "Karim Nassar", "Racking pushed to Monday."),
    )
    for item in items:
        assert item.origin_id in {"1", "2"}
        assert set(item.source_ids) <= {"1", "2"}

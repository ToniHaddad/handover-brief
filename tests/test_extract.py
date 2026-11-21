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


# 2026-04-13 is a Monday.

def test_deadline_moved_twice_keeps_the_whole_chain():
    items = thread(
        ("1", "2026-04-13 10:02", "Nadine Saliba", "Opening stock count at WH-14 is Thursday."),
        ("2", "2026-04-15 08:40", "Georges Abi Nader", "Count pushed to Monday, the FA-2026 trucks arrive Thursday."),
        ("3", "2026-04-17 08:41", "Nadine Saliba", "Then the count is now Wednesday the 22nd."),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 4, 22)
    assert [v.value for v in d.history if v.kind in ("set", "moved")] == ["2026-04-16", "2026-04-20", "2026-04-22"]
    assert [v.message_id for v in d.history if v.kind == "moved"] == ["2", "3"]
    assert [v.author for v in d.history if v.kind == "moved"] == ["Georges Abi Nader", "Nadine Saliba"]
    assert d.changed


def test_correction_by_the_author_replaces_the_date():
    items = thread(
        ("1", "2026-04-14 09:40", "Fadi Sleiman", "I'll print the shelf labels. Ready by the 23rd."),
        ("2", "2026-04-14 09:44", "Fadi Sleiman", "sorry, I meant the 24th. The printer is in Beirut until Thursday.", "1"),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 4, 24)
    assert d.history[-1].kind == "corrected"


def test_move_that_nobody_agreed_to_does_not_change_the_deadline():
    items = thread(
        ("1", "2026-09-14 15:30", "Layla Frem", "Hygiene kit distribution in S-01 and S-02 on Saturday 19 September."),
        ("2", "2026-09-17 16:00", "Nour Kassab", "Could we push the kit distribution to Monday? Saturday is hard for volunteers."),
        ("3", "2026-09-17 16:12", "Layla Frem", "No, families have been without soap for four days. Saturday stays.", "2"),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 9, 19)
    [p] = of(items, "proposal")
    assert p.origin_id == "2" and p.status == "not_agreed"
    assert not of(items, "decision")


def test_agreed_move_changes_the_deadline_and_records_who_agreed():
    items = thread(
        ("1", "2026-04-13 08:41", "Nadine Saliba", "WH-14 gets unlocked in the stock system on 4 May."),
        ("2", "2026-04-20 09:00", "Rami Khoury", "Can we move the unlock to Wednesday 6 May?"),
        ("3", "2026-04-20 09:12", "Nadine Saliba", "OK, 6 May.", "2"),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 5, 6)
    assert ("agreed", "3", "Nadine Saliba") in [(v.kind, v.message_id, v.author) for v in d.history]
    assert not of(items, "proposal")


def test_proposal_without_agreement_is_never_a_decision():
    items = thread(
        ("1", "2026-09-16 10:20", "Nour Kassab", "Should we open a fourth shelter in the Minieh school?"),
        ("2", "2026-09-16 11:00", "Bilal Hamdan", "Bebnine road open again since 10."),
        ("3", "2026-09-17 07:05", "Omar Daher", "DSP-2026-00417 out: 150 mattresses to S-03."),
    )
    assert not of(items, "decision")
    [p] = of(items, "proposal")
    assert p.status == "not_agreed"


def test_agreement_must_come_from_another_person():
    items = thread(
        ("1", "2026-04-14 09:20", "Georges Abi Nader", "Let's print QR labels per shelf location, not per box."),
        ("2", "2026-04-14 09:21", "Georges Abi Nader", "ok"),
    )
    assert not of(items, "decision")
    assert len(of(items, "proposal")) == 1


def test_proposal_agreed_by_another_person_is_a_decision():
    items = thread(
        ("1", "2026-04-14 09:20", "Georges Abi Nader", "Let's print QR labels per shelf location, not per box."),
        ("2", "2026-04-14 09:31", "Nadine Saliba", "Makes sense, per shelf.", "1"),
    )
    [d] = of(items, "decision")
    assert d.status == "in_force" and d.source_ids == ["1", "2"]


def test_hedged_reply_is_not_agreement():
    items = thread(
        ("1", "2026-04-14 11:15", "Fadi Sleiman", "What if we count on a Saturday so the warehouse stays open?"),
        ("2", "2026-04-14 11:30", "Nadine Saliba", "Possibly. I need to check the overtime rules.", "1"),
    )
    assert not of(items, "decision")
    assert len(of(items, "proposal")) == 1


def test_later_decision_reverses_the_earlier_one():
    items = thread(
        ("1", "2026-09-14 13:10", "Layla Frem", "Let's dispatch blankets from WH-11 for the Halba shelters."),
        ("2", "2026-09-14 13:18", "Omar Daher", "Agreed.", "1"),
        ("3", "2026-09-15 14:10", "Layla Frem", "WH-11 is short. Let's switch blanket dispatches for Halba to WH-07 instead."),
        ("4", "2026-09-15 14:16", "Omar Daher", "Yes, switch.", "3"),
    )
    old, new = of(items, "decision")
    assert old.status == "reversed" and old.target == new.id
    assert new.status == "in_force"


def test_announced_decision_counts_without_a_reply():
    items = thread(
        ("1", "2026-09-14 11:00", "Layla Frem", "Decision from the coordinator: all dispatches go on EA-2026."),
    )
    [d] = of(items, "decision")
    assert d.status == "in_force"


def test_cancellation_marks_the_dated_event_cancelled():
    items = thread(
        ("1", "2026-09-14 18:52", "Layla Frem", "Send 150 mattresses from WH-07 to S-03 on 15 September, first thing."),
        ("2", "2026-09-15 08:12", "Layla Frem", "Road closed. The S-03 mattress delivery is cancelled for today."),
        ("3", "2026-09-15 08:15", "Omar Daher", "ok, cancelling the loading", "2"),
    )
    [d] = of(items, "deadline")
    assert d.status == "cancelled"
    [c] = of(items, "cancellation")
    assert c.target == d.id and c.source_ids == ["2", "3"]


def test_cancelled_task_takes_its_owner_with_it():
    items = thread(
        ("1", "2026-04-15 10:12", "Georges Abi Nader", "The scanner is dead. Leave it with me, I'll order a new one."),
        ("2", "2026-04-24 10:00", "Georges Abi Nader", "We don't need the scanner after all. Dropping that task.", "1"),
    )
    [o] = of(items, "owner")
    assert o.status == "cancelled"


def test_cancelling_one_thing_leaves_what_is_still_on():
    items = thread(
        ("1", "2026-04-13 09:00", "Nadine Saliba", "Keeper training goes next Monday with the Baalbek session."),
        ("2", "2026-04-14 08:45", "Rami Khoury", "The Baalbek session is cancelled. Keeper training still goes next Monday."),
    )
    [d] = of(items, "deadline")
    assert d.status == "current"


def test_claimed_task_and_accepted_request_make_owners():
    items = thread(
        ("1", "2026-04-13 08:55", "Hiba Mansour", "I'll map the WH-14 item names to catalogue codes."),
        ("2", "2026-04-13 11:30", "Nadine Saliba", "@Rami can you create the keeper accounts?"),
        ("3", "2026-04-13 11:48", "Rami Khoury", "Sure, will have them by Thursday.", "2"),
        ("4", "2026-04-13 11:50", "Nadine Saliba", "@Joumana can you check the INKIND pallets?"),
    )
    owners = {o.owner: o for o in of(items, "owner")}
    assert set(owners) == {"Hiba Mansour", "Rami Khoury"}  # Joumana never accepted
    assert owners["Rami Khoury"].origin_id == "2"
    [d] = of(items, "deadline")
    assert d.date == date(2026, 4, 16)


def test_takeover_supersedes_the_previous_owner():
    items = thread(
        ("1", "2026-09-14 15:41", "Sami Rahal", "I'll prepare the hygiene kits at WH-11."),
        ("2", "2026-09-16 08:20", "Layla Frem", "@Omar can you take over the hygiene kits, Sami is off sick?"),
        ("3", "2026-09-16 08:35", "Omar Daher", "Yes, I'll take it over.", "2"),
    )
    sami, omar = of(items, "owner")
    assert sami.status == "superseded" and omar.status == "current"


def test_unanswered_question_is_listed_and_answered_one_is_not():
    items = thread(
        ("1", "2026-04-15 09:30", "Fadi Sleiman", "Do we record the damaged cartons as damage reports before go-live?"),
        ("2", "2026-04-15 09:32", "Georges Abi Nader", "anyone going to the bakery? manouche for the team"),
        ("3", "2026-04-16 09:00", "Nadine Saliba", "Is the forklift included in the quote?"),
        ("4", "2026-04-16 09:05", "Georges Abi Nader", "No, it's separate.", "3"),
        ("5", "2026-04-16 09:30", "Hiba Mansour", "Has the admin seen the code list?"),
        ("6", "2026-04-16 09:40", "Rami Khoury", "Yes, he signed it off."),
    )
    qs = of(items, "question")
    assert [q.origin_id for q in qs] == ["1"]  # the bakery chatter is not a handover question


def test_question_answered_only_by_side_chatter_stays_open():
    items = thread(
        ("1", "2026-09-15 09:00", "Layla Frem", "Has anyone confirmed the blankets reached S-02?"),
        ("2", "2026-09-15 09:15", "Carla Nassif", "no coffee left at S-01, if anyone passes by the station"),
        ("3", "2026-09-15 10:10", "Omar Daher", "DSP-2026-00414 out: 200 mattresses to S-02."),
    )
    assert [q.origin_id for q in of(items, "question")] == ["1"]


def test_every_item_points_at_real_messages():
    items = thread(
        ("1", "2026-04-13 10:02", "Nadine Saliba", "Count done by Thursday."),
        ("2", "2026-04-15 08:40", "Georges Abi Nader", "Count pushed to Monday."),
    )
    for item in items:
        assert item.origin_id in {"1", "2"}
        assert set(item.source_ids) <= {"1", "2"}


def test_arabic_agreement_to_a_proposed_date_keeps_the_proposed_day():
    items = thread(
        ("1", "2026-04-16 15:10", "Rami Khoury", "Keeper training on the phone app on Tuesday 28 April in Zahle?"),
        ("2", "2026-04-16 15:22", "Georges Abi Nader", "تمام، الثلاثاء منيح", "1"),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 4, 28)  # not the bare "Tuesday" of the reply (21 April)


def test_french_cancellation_finds_its_target_by_code():
    items = thread(
        ("1", "2026-04-15 11:05", "Joumana Azar", "Transfer of 40 boxes of hygiene kits to WH-09 is planned for Thursday 23 April."),
        ("2", "2026-04-23 08:15", "Joumana Azar", "Le transfert vers WH-09 de jeudi est annulé, ils n'ont plus de place."),
    )
    [d] = of(items, "deadline")
    assert d.status == "cancelled"


def test_arabic_question_without_answer_is_open():
    items = thread(
        ("1", "2026-04-15 14:02", "Fadi Sleiman", "مين معو مفتاح غرفة التبريد؟"),
        ("2", "2026-04-16 09:00", "Nadine Saliba", "Trucks are here."),
    )
    assert [q.origin_id for q in of(items, "question")] == ["1"]


def test_person_off_work_is_not_a_cancellation():
    items = thread(
        ("1", "2026-04-20 09:20", "Fadi Sleiman", "Could we unlock on Friday 1 May?"),
        ("2", "2026-04-20 09:28", "Nadine Saliba", "No, 1 May is a holiday and the admin is off.", "1"),
    )
    assert not of(items, "cancellation")
    assert len(of(items, "proposal")) == 1


def test_tonight_in_a_report_is_not_a_deadline():
    items = thread(
        ("1", "2026-09-14 18:40", "Carla Nassif", "A third school opened tonight, S-03 Bebnine. 90 families."),
        ("2", "2026-09-14 18:52", "Layla Frem", "Dispatch 150 mattresses to S-03 this evening."),
    )
    assert [d.origin_id for d in of(items, "deadline")] == ["2"]


# ---- rules added after rent-renewals moved into the tuning set

def test_curly_apostrophes_in_cues():
    items = thread(
        ("1", "2026-01-20 13:25", "Dalia Akl", "Can we put March 10 as the deadline for clearing the Saida renewal?"),
        ("2", "2026-01-20 13:33", "Karim Nahle", "D\u2019accord pour le 10 mars, \u00e7a nous laisse assez de marge.", "1"),
        ("3", "2026-01-20 14:00", "Maya Tannous", "I\u2019ll draft the renewal letter for Saida."),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 3, 10) and d.origin_id == "1"
    assert not of(items, "proposal")
    assert [o.owner for o in of(items, "owner")] == ["Maya Tannous"]


def test_two_dates_for_two_things_in_one_message():
    items = thread(
        ("1", "2026-01-12 08:51", "Maya Tannous",
         "Zahle centre, RENT-ZAH-03: contract ends April 16. Our follow-up is set for March 26 in the Sheet."),
    )
    assert sorted(d.date for d in of(items, "deadline")) == [date(2026, 3, 26), date(2026, 4, 16)]


def test_correction_that_states_the_new_value_supersedes_the_old_date():
    items = thread(
        ("1", "2026-01-12 08:51", "Maya Tannous",
         "Zahle centre, RENT-ZAH-03: contract ends April 16. Our follow-up is set for March 26 in the Sheet."),
        ("2", "2026-01-13 09:09", "Rima Zoghbi", "The March 26 follow-up doesn't match the contract.", "1"),
        ("3", "2026-01-13 09:14", "Maya Tannous",
         "Right, the follow-up was copied from another row. Corrected it in the Sheet to January 16, "
         "three months before April 16.", "2"),
    )
    by_date = {d.date: d for d in of(items, "deadline")}
    assert set(by_date) == {date(2026, 1, 16), date(2026, 4, 16)}  # the contract end is untouched
    follow = by_date[date(2026, 1, 16)]
    assert [v.kind for v in follow.history if v.kind != "mentioned"] == ["set", "corrected"]


def test_should_be_x_not_y_is_a_correction():
    items = thread(
        ("1", "2026-06-17 09:00", "Nadia Fares", "Recount at WH-22 is set for the 2nd of July."),
        ("2", "2026-06-17 09:30", "Ziad Moukarzel", "The recount date in the sheet should be the 9th, not the 2nd."),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 7, 9) and d.history[-1].kind == "corrected"


def test_cancellation_attaches_to_the_event_it_names_not_to_another_on_the_same_day():
    items = thread(
        ("1", "2026-09-17 14:00", "Carla Nassif", "Hygiene kit distribution in S-01 and S-02 is now Saturday the 19th."),
        ("2", "2026-09-18 09:00", "Layla Frem",
         "La visite du gouverneur aux \u00e9coles pr\u00e9vue samedi est annul\u00e9e, il reste \u00e0 Tripoli."),
    )
    [d] = of(items, "deadline")
    assert d.status == "current"
    [c] = of(items, "cancellation")
    assert c.target is None


def test_cancelled_visit_takes_both_its_date_and_its_owner():
    items = thread(
        ("1", "2026-01-19 14:20", "Rima Zoghbi", "Halba site visit is Thursday. I'll take the visit and check the folder."),
        ("2", "2026-01-21 09:08", "Dalia Akl", "On annule la visite \u00e0 Halba. Le magasin est ferm\u00e9.", "1"),
    )
    [d] = of(items, "deadline")
    [o] = of(items, "owner")
    assert d.status == "cancelled" and o.status == "cancelled"


def test_later_decision_on_the_same_thing_with_a_different_code_reverses_the_earlier_one():
    items = thread(
        ("1", "2026-01-13 09:38", "Karim Nahle", "For the Tripoli warehouse, let's charge the whole rent to EA-2026."),
        ("2", "2026-01-13 09:42", "Dalia Akl", "ok", "1"),
        ("3", "2026-01-20 10:32", "Karim Nahle", "Let's cover the Jbeil rent entirely from WASH-2026."),
        ("4", "2026-01-20 10:41", "Dalia Akl", "Fine by me.", "3"),
        ("5", "2026-01-26 14:32", "Dalia Akl", "Pour Tripoli, je propose de mettre tout le loyer sur FA-2026."),
        ("6", "2026-01-26 14:37", "Karim Nahle", "tamam, agreed.", "5"),
    )
    tripoli_old, jbeil, tripoli_new = of(items, "decision")
    assert tripoli_old.status == "reversed" and tripoli_old.target == tripoli_new.id
    assert jbeil.status == "in_force" and tripoli_new.status == "in_force"


def test_question_starting_with_which_is_not_a_proposal():
    items = thread(
        ("1", "2026-01-22 10:38", "Karim Nahle", "Which cost centre should we use for Halba's municipal fee?"),
        ("2", "2026-01-23 09:00", "Tarek Choueiri", "Generator is down again."),
    )
    assert not of(items, "proposal")
    assert [q.origin_id for q in of(items, "question")] == ["1"]


def test_wont_work_turns_a_proposed_date_down():
    items = thread(
        ("1", "2026-01-14 09:06", "Dalia Akl", "Finance needs the budget pack next Monday."),
        ("2", "2026-01-14 09:17", "Tarek Choueiri", "Could we move the pack to Wednesday instead?", "1"),
        ("3", "2026-01-14 09:20", "Dalia Akl", "Wednesday won't work for finance. Keep Monday for now.", "2"),
    )
    [d] = of(items, "deadline")
    assert d.date == date(2026, 1, 19)
    [p] = of(items, "proposal")
    assert p.history[-1].kind == "rejected"

# Labelling rules

The gold files list what a careful colleague would write in a handover after
reading the whole thread. The benchmark compares the tool's output with them.
These rules were fixed before the held-out thread was labelled.

## Item types

**deadline**: a date by which something must happen, or a dated event the
team committed to (a distribution day, a delivery, a meeting). It counts when
it is stated as a plan or fact, or when it was proposed and another person
agreed. Not a deadline: someone's own availability ("I'm off Friday"), a past
event being reported, a vague time ("next week", "soon"), or a proposed date
nobody agreed to (that is a proposal).

- `chain`: every value the date took, oldest first, as ISO dates. A move
  ("pushed to Monday") and a correction ("sorry, I meant the 15th") both add
  a value. A proposed move nobody agreed to does not.
- `status`: `current`, or `cancelled` if the task or event was called off.

**decision**: a proposal followed by agreement from at least one other
person, or a decision announced as already made ("we have decided", "final
answer from the country director: ..."). An agreed date is a deadline, not a
decision. An agreed move of an existing deadline is a step in that deadline's
chain, not a decision.

- `status`: `in_force`, or `reversed` when a later agreed or announced
  decision replaced it. A reversed decision names the replacing message in
  `superseded_by`; the replacing decision is its own item.

**proposal**: a suggestion nobody else agreed to (ignored, or explicitly
turned down). This includes proposed new dates for an existing deadline that
were not agreed. These must never be shown as decisions.

**owner**: a person took responsibility for a task, either by claiming it
("I'll take it", "leave it with me") or by accepting a request ("@Daniel can
you ...?" then "yes, on it" from Daniel). A request nobody accepted is not an
owner item.

- `owner`: the person's name as it appears in `from`.
- `status`: `current`, or `superseded` if someone else took the task over, or
  `cancelled` if the task was called off.

**question**: a question that needed an answer and got none anywhere later in
the thread. Not: questions that were answered (in words or by someone doing
the thing), social chatter ("anyone want coffee?"), rhetorical questions,
proposals phrased as questions ("should we ...?"), and requests ("can you
...?").

**cancellation**: a message that calls off a task, meeting or delivery.
`target` (optional) is the id of the message that set up the cancelled thing.

## Matching

Each gold item has `match_ids`: the message ids where a reader would say the
item starts. For a deadline or decision that is the message that first
proposed or stated it; the agreeing message may be listed too. A predicted
item matches a gold item when the types agree, the predicted origin message
is in `match_ids`, and:

- deadline: the predicted current date equals the last value of `chain`;
- decision: the predicted status (`in_force` or `reversed`) agrees;
- owner: the predicted owner name agrees;
- the other types need only the message.

Changes are scored from the same items: a gold change is a deadline whose
chain has more than one value, a reversed decision, or a superseded owner.
A predicted change matches when the item matches and, for deadlines, the
whole chain agrees.

## File format

```json
{
  "thread": "warehouse-move",
  "items": [
    {"type": "deadline", "label": "Racking installed at new site",
     "match_ids": ["m014"], "chain": ["2026-03-13", "2026-03-16"],
     "status": "current"},
    {"type": "decision", "label": "Use Bekaa Freight for the move",
     "match_ids": ["m020", "m021"], "status": "in_force"},
    {"type": "proposal", "label": "Weekend shift to move pallets",
     "match_ids": ["m033"]},
    {"type": "owner", "label": "Book forklift hire", "match_ids": ["m040"],
     "owner": "Daniel Mensah", "status": "current"},
    {"type": "question", "label": "Who holds the keys to the old site?",
     "match_ids": ["m055"]},
    {"type": "cancellation", "label": "Thursday site visit called off",
     "match_ids": ["m077"], "target": "m061"}
  ]
}
```

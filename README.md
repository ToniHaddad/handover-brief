# handover-brief

Turns weeks of team chat into a handover timeline where every decision and deadline links to the message that set it, including the ones that changed.

![The brief for a warehouse move: the racking deadline is selected, its history shows Friday, then Monday, then Wednesday, and the thread on the right highlights the message where Karim moved it to Monday](docs/brief-moved-deadline.png)

## The need

When someone takes over a project, they inherit weeks of channel messages and have to rebuild the state of play: what was decided, what is due when, what is still open. A summary loses the detail that matters most: the deadline that was moved from Friday to Monday in message 25, or the supplier choice that was reversed a week later. This tool lists each deadline, decision, open question, cancellation and unagreed proposal, and every item opens the exact message it came from, with its full change history beside it.

There is no language model in this tool. Extraction is a fixed set of rules, so every claim can be traced to a message and every behaviour can be tested. The trade-off is that the rules miss phrasings they have not seen; the held-out results below show how often.

## Try it

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -e .
handover serve
```

```
Serving 3 threads on http://127.0.0.1:8102/  (Ctrl+C to stop)
```

Open http://127.0.0.1:8102/, pick a thread, click any item. For a single file you can email or put on a shared drive:

```
handover build data/threads/warehouse-move.json --out brief.html
```

```
97 messages -> 33 items (3 cancellation, 11 deadline, 4 decision, 10 owner, 3 proposal, 2 question)
wrote brief.html (67 KB, self-contained)
```

The page has no external requests (no CDN, no fonts to download), works at phone width and has light and dark themes. `handover items <thread.json>` prints the items as a table ([sample](docs/sample-output.txt)). `python -m handover` is the same command if your system blocks the generated launcher.

<img src="docs/mobile-source.png" alt="On a phone, the selected deadline opens a panel with its history and the highlighted message 'Racking pushed to Monday'" width="300">

## How it works

The input is a thread in a small JSON format modelled on a Microsoft Teams channel export: message id, author, timestamp, text, reply-to id, edited flag ([docs/schema.md](docs/schema.md)).

| Step | What it does |
|---|---|
| Resolve dates | Every date phrase is resolved against the timestamp of the message that contains it: "Friday", "next Monday", "the 14th", "end of day tomorrow", "in two weeks", "10/04", "April 10". Rules are in [dates.py](handover/dates.py), for example "next Monday" said on a Wednesday is 5 days later. |
| Describe each message | Cue patterns mark proposals, agreement, disagreement, requests, claims ("I'll take it"), moves ("pushed to"), corrections ("sorry, I meant the 18th"), cancellations and announced decisions. |
| One pass, in order | A state machine keeps what a careful reader keeps in mind: current deadlines, open proposals, pending requests. A move changes the deadline it refers to (found by reply link, the old date, or shared words) and appends to its history. A proposal becomes a decision only when **another person** agrees; a proposed date change nobody agreed to leaves the deadline as it was. A later decision on the same topic with a reversal cue ("switch", "revised") marks the earlier one reversed. |
| Unanswered questions | A question with no reply, and no on-topic answer from someone else in the next few messages, is listed as open. Side chatter is ignored. |
| Render | Items and messages are embedded as JSON in one HTML page. Clicking an item highlights its messages and scrolls to the first change. |

Each item keeps the ids of all its source messages and a history of versions (set, moved, corrected, agreed, cancelled, reversed, handed over), with author and message for each step.

## Results

Three synthetic threads from fictional Northbridge Relief teams, 69 to 97 messages each, with gold labels written by the rules in [docs/labelling.md](docs/labelling.md). I wrote and tuned on two of them (a warehouse move in Lebanon, a cash distribution in Kenya). The third (a donor report in Colombia) was written, with its gold labels, by a different language model from the same written rules, before any extraction code existed. It was committed first, not read while tuning, and measured once ([docs/heldout-first-run.txt](docs/heldout-first-run.txt)). The extractor has not changed since that run.

Output of `handover bench` ([docs/benchmark.txt](docs/benchmark.txt)):

```
== tune (warehouse-move, cash-distribution) ==
type          gold found right  precision  recall
deadline        20    20    19       0.95    0.95
decision         9     9     9       1.00    1.00
proposal         6     6     6       1.00    1.00
owner           21    22    21       0.95    1.00
question         4     4     4       1.00    1.00
cancellation     5     5     5       1.00    1.00
change           9     9     9       1.00    1.00
all items       65    66    64       0.97    0.98
Superseded, cancelled or unagreed items shown as current: 0 (out of 19 such items in gold)

== heldout (donor-report) ==
type          gold found right  precision  recall
deadline         7     8     7       0.88    1.00
decision         4     3     3       1.00    0.75
proposal         2     3     2       0.67    1.00
owner            4     2     2       1.00    0.50
question         3     4     3       0.75    1.00
cancellation     1     1     1       1.00    1.00
change           3     2     2       1.00    0.67
all items       21    21    18       0.86    0.86
Superseded, cancelled or unagreed items shown as current: 1 (out of 6 such items in gold)
  ! d007 deadline 'Q1 report kickoff is Thursday at 10.' shown as current
```

A match needs the right type, the right source message and the right value (the current date for a deadline, the status for a decision, the person for an owner; a change needs the whole chain of dates). The last line of each block is the number that matters most for a handover: how many items the brief presents as current although they were superseded, cancelled or never agreed.

Read the tuned numbers as "the rules do what they were written to do". The held-out numbers are the honest estimate, and they come from 21 gold items, so one item moves recall by about 5 points.

## Where it fails

Every case below is from the held-out thread.

![The held-out brief lists the Q1 kickoff as a current deadline, although message 19 called it off](docs/heldout-failure.png)

- **A cancelled meeting shown as current.** "Calling off the kickoff this morning. No need to join if the hold is still showing." (#19, a reply to the kickoff message). A rule meant to protect things that are "still on" ("the cleaning crew is cancelled, furniture still goes Monday") saw "still" and the word "hold", which also appears in the kickoff message, and excluded the kickoff from being cancelled. The cancellation is listed, but the kickoff also stays under current deadlines. This is the one stale item.
- **A proposal phrased as an opinion.** "I'd put the results table in the narrative body" (#10) is not a proposal cue the rules know, so "fine by me" (#11) had nothing to agree with. When the team later moved the table to Annex A (#45, #46), that showed up as a new decision and the reversal was lost from "things that changed".
- **Ownership in other words.** "sí, narrative is mine" (#5) and "Leave the financial workbook with me" (#6) were not recognised; the rules know "leave it with me" and a list of "I'll ..." verbs. Two of four owners missed.
- **A question read as a proposal.** "Are the annex headings locked by the donor or can we change them?" (#53) contains "can we", so it was listed as an unagreed proposal.
- **A past event read as a deadline.** "Hartwell acknowledged both files this morning." (#87) "This morning" resolves to the message date and became a deadline.
- **Banter read as an open question.** "only 14? showoff" (#86).

One miss in the tuning set is by design: "share the PDM report within two weeks of the survey starting" is relative to another event, not the message, so the resolver refuses to guess a date rather than give a wrong one.

## What I would add next

- Fix the six cases above, then write a new held-out thread, because this one is no longer unseen.
- A converter from a real Teams or Slack export (HTML stripped, threads flattened) into the thread format.
- An LLM pass could propose items the rules miss, with the rules and the source links kept as the check on what it may claim.
- Arabic and French cue lists and date phrases ("الجمعة", "vendredi prochain").

## Licence

MIT. All threads and people are synthetic; Northbridge Relief is a fictional organisation.

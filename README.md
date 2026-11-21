# handover-brief

Turns weeks of team chat into a handover timeline where every decision and deadline links to the message that set it, including the ones that changed.

![The brief for a warehouse go-live: the opening stock count is selected, its history shows Thursday, then Monday, then Wednesday, and the thread on the right highlights the message where Georges pushed the count to Monday](docs/brief-moved-deadline.png)

## The need

In a humanitarian organization in Lebanon, much of the coordination happens in team chats, in Arabic, English and French: bringing a warehouse into the stock system, running an emergency operations room when shelters open in schools, following up rent contracts before they expire. When someone goes on leave or a new colleague takes over, they inherit weeks of messages and have to rebuild what is due when, what was agreed and what was called off. A summary loses the detail that matters most: the stock count that moved from Thursday to Monday, the delivery cancelled when the road closed, the follow-up date in the sheet that turned out to be wrong.

This tool lists each deadline, decision, open question, cancellation and unagreed proposal, and every item opens the exact message it came from, with its full change history beside it. There is no language model: extraction is a fixed set of rules, so every claim can be traced to a message and every behaviour can be tested. The trade-off is that the rules miss phrasings they have not seen; the held-out results below show how often.

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

Open http://127.0.0.1:8102/, pick a thread, click any item. For a single file you can send by email or put on a shared drive:

```
handover build data/threads/warehouse-golive.json --out brief.html
```

```
78 messages -> 25 items (2 cancellation, 8 deadline, 4 decision, 7 owner, 2 proposal, 2 question)
wrote brief.html (58 KB, self-contained)
```

The page makes no external requests (no CDN, no web fonts), so it opens on a weak connection or none. It works at phone width, in light and dark. `handover items <thread.json>` prints the items as a table ([sample](docs/sample-output.txt)). `python -m handover` is the same command if your system blocks the generated launcher.

<img src="docs/mobile-source.png" alt="On a phone, the selected stock count opens a panel with its history and the highlighted message 'Count pushed to Monday'" width="300">

## How it works

The input is a chat thread in a small JSON format: message id, author, timestamp, text, reply-to id, edited flag ([docs/schema.md](docs/schema.md)). Field names follow the Microsoft Graph chat message format, so an export from most chat tools converts with a short script.

| Step | What it does |
|---|---|
| Resolve dates | Every date phrase is resolved against the timestamp of the message that contains it: "Friday", "next Monday", "the 14th", "end of day tomorrow", "in two weeks", "10/04", "April 10", and the French and Arabic equivalents ("lundi prochain", "le 14 avril", "dans deux semaines", "الاثنين الجاي", "بكرا"). Rules are in [dates.py](handover/dates.py). |
| Describe each message | Cue patterns in English, French and Arabic mark proposals, agreement, disagreement, requests, claims ("I'll take it", "je m'en occupe"), moves ("pushed to", "reporté à"), corrections, cancellations ("annulé", "ملغى") and announced decisions. Codes such as WH-07, S-03 or FA-2026 are kept whole, because they name the thing a message is about. |
| One pass, in order | A state machine keeps what a careful reader keeps in mind: current deadlines, open proposals, pending requests. A move changes the deadline it refers to (found by reply link, the old date, or shared words) and appends to its history. A proposal becomes a decision only when **another person** agrees; a proposed date change nobody agreed to leaves the deadline as it was. A later decision on the same topic with a reversal cue marks the earlier one reversed. |
| Unanswered questions | A question (ending in `?` or `؟`) with no reply, and no on-topic answer from someone else in the next few messages, is listed as open. Side chatter is ignored. |
| Render | Items and messages are embedded as JSON in one HTML page. Clicking an item highlights its messages and scrolls to the first change. |

Each item keeps the ids of all its source messages and a history of versions (set, moved, corrected, agreed, cancelled, reversed, handed over), with author and message for each step.

## Results

Three synthetic threads, 70 to 83 messages each, with gold labels written by the rules in [docs/labelling.md](docs/labelling.md): a warehouse joining the stock system (stock count, catalogue codes, QR labels, keeper training, the unlock day), an emergency operations room (shelters in schools, urgent dispatches, a delivery cancelled when a road closed), and rent renewals (contracts ending in three months, next year's budget lines, a wrong follow-up date, a landlord who never answers). Each has Arabic and French messages.

I wrote the first two and tuned the rules on them only ([baseline before tuning](docs/tune-baseline.txt): precision 0.77, recall 0.69). The rent-renewals thread and its gold labels were written by a different language model from the same written rules and committed before any rule change. I checked only its structure, then measured it once ([docs/heldout-first-run.txt](docs/heldout-first-run.txt)). After that run I found that the scorer ignored a deadline's status; I fixed the scorer, not the extractor, and rescored. Both runs are in that file and the extractor has not changed since.

Output of `handover bench` ([docs/benchmark.txt](docs/benchmark.txt)):

```
== tune (warehouse-golive, emergency-ops) ==
type          gold found right  precision  recall
deadline        16    17    15       0.88    0.94
decision         7     7     7       1.00    1.00
proposal         5     5     5       1.00    1.00
owner           14    15    14       0.93    1.00
question         4     4     4       1.00    1.00
cancellation     4     4     4       1.00    1.00
change           7     7     7       1.00    1.00
all items       50    52    49       0.94    0.98
Superseded, cancelled or unagreed items shown as current: 0 (out of 14 such items in gold)
Current items shown as cancelled, reversed or handed over: 1 (out of 33 current items in gold)

== heldout (rent-renewals) ==
type          gold found right  precision  recall
deadline        12    14     9       0.64    0.75
decision         4     3     2       0.67    0.50
proposal         2     6     2       0.33    1.00
owner            7     7     6       0.86    0.86
question         3     2     2       1.00    0.67
cancellation     1     1     1       1.00    1.00
change           4     2     2       1.00    0.50
all items       29    33    22       0.67    0.76
Superseded, cancelled or unagreed items shown as current: 3 (out of 8 such items in gold)
Current items shown as cancelled, reversed or handed over: 0 (out of 20 current items in gold)
```

A match needs the right type, the right source message and the right value (date and status for a deadline, status for a decision, person and status for an owner; a change needs the whole chain of dates). The two last lines of each block are the errors that hurt a handover most: something stale presented as current, and something still on presented as cancelled.

Read the tuned numbers as "the rules do what they were written to do". The held-out numbers are the honest estimate. They are worse than in this project's earlier scenario (held-out precision 0.86, recall 0.86, 1 stale item out of 6) on a thread with three languages, and they come from 29 gold items, so one item moves recall by about 3 points.

**Arabic and French.** Of the dozen Arabic and French messages in the held-out thread, the rules handled an Arabic agreement ("تمام، موافقة"), an Arabic acceptance of a task, an Arabic and a French open question, a French deadline ("Dans deux semaines, il faut avoir vérifié les codes") and a French proposal ("je propose de basculer"). They missed two French agreements written with a typographic apostrophe (D’accord instead of D'accord), the French verb "basculer" as a sign that a decision was reversed, and they linked a French cancellation to the wrong item (see below).

## Where it fails

From the held-out thread:

![The rent-renewals brief still lists the wrong March 26 follow-up date as current, and the corrected January 16 date as a separate deadline on 16 April](docs/heldout-failure.png)

- **The wrong follow-up date stays current.** Message #2 holds two dates ("contract ends April 16. Our follow-up is set for March 26"); the rules make one deadline per message and kept the follow-up. The fix came as "Corrected it in the Sheet to January 16, three months before April 16" (#9). "Corrected it" is not a correction cue the rules know, so it became a new deadline, and "before April 16" outranked "to January 16", so even that one is dated 16 April.
- **A typographic apostrophe.** "D’accord, on garde les lignes sans date" (#32) and "D’accord pour le 10 mars" (#42) were not read as agreement. One decision is listed as an unagreed proposal; an agreed date is listed as a proposal and reappears later as a fresh deadline.
- **A French reversal.** "je propose de basculer tout le loyer ... sur FA-2026" became a decision, but "basculer" is not a reversal cue, so the old EA-2026 decision is still shown in force beside it.
- **A cancellation linked to the wrong item.** "On annule la visite à Halba" (#44) replied to a message that set both a visit date and an owner ("I'll take the visit"); it cancelled the owner and left the visit under current deadlines.
- **A question read as a proposal.** "Which cost centre should we use for Halba's municipal fee?" (#51) contains "should we". The same failure appeared in this project's earlier held-out run, and I did not fix it while tuning.
- **A refusal read as a deadline.** "Wednesday won't work for finance" (#19) is not in the disagreement cues.

From a tuning thread, still unfixed:

- **A date match cancels the wrong event.** "La visite du gouverneur aux écoles prévue samedi est annulée" cancelled the governor's Saturday visit, which was never set up in the thread, and the rules attached it to the only Saturday item: the hygiene kit distribution, which then shows as cancelled ([screenshot](docs/tune-failure.png)). I found this after the held-out run and left the rules as they were, so the held-out number stays an unseen measurement.

## What I would add next

- Fix the cases above (one deadline per date in a message, typographic apostrophes, French reversal verbs, cancel both the date and the owner of a task, require more than a shared date before cancelling), then write a new held-out thread.
- A converter from a real chat export (HTML stripped, threads flattened) into the thread format.
- An LLM pass could propose items the rules miss, with the rules and the source links kept as the check on what it may claim.

## Licence

MIT. All threads, people, codes and figures are synthetic; the organization is not named and no real organization's material is used.

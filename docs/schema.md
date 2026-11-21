# Thread format

`handover` reads one channel conversation as a JSON file. The field names
come from the Microsoft Graph `chatMessage` resource that a Teams channel
export uses, flattened so a thread can be written or converted by hand.

```json
{
  "schema": "handover-thread/1",
  "synthetic": true,
  "team": "The Organization, Bekaa logistics",
  "channel": "WH-14 go-live",
  "messages": [
    {
      "id": "m001",
      "createdDateTime": "2026-04-13T08:41:00+03:00",
      "from": "Nadine Saliba",
      "body": "Morning all. Admin confirmed WH-14 gets unlocked in the stock system on 4 May.",
      "replyToId": null,
      "edited": false
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique message id (any string). |
| `createdDateTime` | yes | ISO 8601 with a UTC offset. Relative dates ("Friday", "tomorrow") are resolved against the local date of this timestamp. |
| `from` | yes | Display name of the author. In Graph this is `from.user.displayName`. |
| `body` | yes | Plain text. In Graph this is `body.content` with HTML stripped. `@Name` is a mention. |
| `replyToId` | no | Id of the earlier message this one replies to or quotes. `null` when the author just posted in the channel. |
| `edited` | no | `true` if the message was edited after posting (Graph: `lastModifiedDateTime` later than `createdDateTime`). Shown as a badge. |

Messages must be in the order they were posted. Top-level `team` and
`channel` are shown in the page header. `synthetic: true` marks invented data.

## Gold labels

Each thread can have a gold file `data/gold/<thread>.gold.json` listing the
items a careful human would put in a handover. See
[labelling.md](labelling.md) for the rules and the file format.

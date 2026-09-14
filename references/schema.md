# Normalized record schema

Every piece of communication, regardless of source, gets converted into this shape before it's used in an answer or handed to another skill. This is what makes an email, a call transcript, and a pasted text message comparable in the same query.

```json
{
  "source": "gmail | gong | zoom | webex | otter | m365 | onenote | evernote | text | pasted",
  "type": "email | call | meeting | note | message",
  "timestamp": "2026-08-14T15:30:00-04:00",
  "participants": ["David Hand", "Jane Doe"],
  "account": "Acme Corp",
  "topics": ["renewal", "pricing"],
  "content_type": "full_text | summary",
  "text": "the actual body/transcript/note content, or the summary if that's all the source gave",
  "source_ref": "a link, message ID, or other pointer back to the original, when one exists"
}
```

Notes on filling this in:

- **`content_type` matters as much as `text`.** If a source only gave a summary (see `references/catalog.md` for which ones do this), mark it `"summary"` so the answer can say so, rather than presenting it with the same confidence as a full transcript.
- **`account` and `topics` are inferred, not always given.** For email and transcripts, pull the account name from context (company domain, explicit mention) and assign topics based on what's actually discussed. For pasted content, ask the person for the account/topic if it's not obvious from the text itself — a paste with no tags is much less useful later.
- **`source_ref` can be empty** for something like a pasted text message with no durable link back to its original. That's fine; just don't invent one.
- Keep records atomic — one email, one call, one note — rather than merging several into one record. Synthesis happens at answer time, not at normalization time.

## Handling likely duplicates across synced sources

Some sources re-store communication that already lives elsewhere — most commonly a CRM (Salesforce, HubSpot) logging an email or call that also exists natively in Gmail, Gong, Zoom, etc. `references/catalog.md`'s "Watch for duplicates" note covers when to check for this; this is what to do with a match once found.

- **Clear match** (same type, overlapping participants, timestamps within about 15 minutes): keep one record, not two. Prefer whichever has `"content_type": "full_text"` over `"summary"` — a CRM-logged copy is often a synced-in summary of something that has the full version natively elsewhere. Mention in the answer that a duplicate was folded in and which source it came from, so the person knows the record count reflects real distinct communications, not double-counting.
- **Possible but unclear match**: don't force it. Show both records and note the possible overlap in the answer ("these two may be the same call — flagging rather than merging since I'm not sure") rather than guessing wrong in either direction.
- Never silently drop a record because it might be a duplicate without saying so, and never merge two records into one without saying that happened — both are the kind of quiet judgment call this skill is supposed to avoid making unannounced.

## Tagging pasted content

When someone pastes in a transcript, email, or note, ask (or infer, and confirm) at minimum: which account and person(s) it relates to, and roughly when it happened if that's not in the text. Without that, a pasted record can't be found again in a later query by account or person, which defeats the point.

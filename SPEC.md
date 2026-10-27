# Clinic Booking API spec
General
- Everything is JSON. Every error response is {"error": "<message>"}.
- Every request needs the X-API-Key header (level 2). Missing or wrong key
  returns 401.

POST /reset (level 1)
  Body: {"slots":[{"id":"s1","provider":"Dr Ade",
  "start":"2026-12-10T09:00:00Z","end":"2026-12-10T09:30:00Z"}]}
  Deletes every booking and replaces all slots with the ones sent, including
  slots in the past. Returns 200.

GET /slots (level 1)
  Optional query: provider (exact match). 200: {"slots":[{id, provider, start,
  end, available}]}, earliest start first. available is false while the slot
  has a confirmed booking.

POST /bookings
  Body: {"slot_id","name","email"}. 201 returns a booking:
  {id, slot_id, name, email, status:"confirmed", created_at}. id is any
  unique id.
  Level 2: 400 if slot_id, name or email is missing or empty, or the email is
    not valid. 404 if the slot does not exist. 400 if the slot has already
    started. Trim spaces from name and email; store email in lower case.
  Level 3: a slot that already has a confirmed booking returns 409. Must hold
    when many requests arrive at the same moment.
  Level 4: optional Idempotency-Key header. Same key + same body returns the
    same response (same status code, same booking id) and never creates a
    second booking. Same key + different body returns 422.
  Level 5: at most 5 attempts per email per minute, failed attempts included.
    The 6th returns 429 with a Retry-After header in whole seconds. Other
    emails are not affected.

GET /bookings (level 4)
  Query: email (required), limit (1 to 50, default 10, anything else returns
  400), cursor. That person's bookings, oldest first, email match ignores
  case. Cursor pagination: pass next_cursor back as cursor for the next page.
  The last page has next_cursor null.
  200: {"bookings":[...],"next_cursor":"..." or null}

GET /bookings/{id} (level 1): 200 booking, 404 if none.
DELETE /bookings/{id} (level 3): sets status to "cancelled" and frees the
  slot. 200 returns the cancelled booking. 404 no such booking. 409 already
  cancelled.

Schemas: Slot {id, provider, start, end} with ISO 8601 UTC date-times.
Booking status is "confirmed" or "cancelled".

# Implementation notes (my decisions, not from the original spec)
- Store slot start/end strings as given and return them as given; parse to
  UTC datetimes for ordering and for "already started" (start <= now).
- POST /bookings processing order: API key (401) -> idempotency lookup ->
  rate limit -> field validation (400) -> slot exists (404) -> slot started
  (400) -> atomic create (409 on conflict) -> store idempotent response.
- Idempotency: key is global; compare bodies after JSON parsing; store status
  and body for every outcome except 401, 429 and 5xx; replays do not count
  toward the rate limit.
- Rate limit: sliding 60 second window keyed by the trimmed lower-case email
  whenever email is a non-empty string; rejected (429) attempts are not
  counted; Retry-After is whole seconds, rounded up, minimum 1, until the
  oldest counted attempt leaves the window.
- /reset also clears idempotency records and rate-limit counters.
- GET /bookings returns bookings of every status; missing email -> 400;
  invalid cursor -> 400.
- /health is exempt from the API key (for Render health checks).
----- end SPEC.md -----

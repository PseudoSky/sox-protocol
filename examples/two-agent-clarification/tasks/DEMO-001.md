# DEMO-001 — Implement POST /login REST endpoint

**Ticket:** DEMO-001
**Channel:** `ticket:DEMO-001`
**Assigned to:** implementer

## Task description

Implement a `POST /login` endpoint for the user authentication service.

The endpoint should:

- Accept `{ "username": str, "password": str }` in the request body.
- Validate credentials against the user store.
- Return a JWT access token on success.
- Return `401 Unauthorized` on failure.

## Deliberately ambiguous requirements

The API spec is silent on the following points:

1. **Token lifetime** — How long should the JWT access token be valid?
   The spec says "issue a JWT" but does not specify expiry. Common choices
   are 15 minutes (short-lived, high security) or 24 hours (long-lived,
   convenience). The security policy document has not been shared with
   the implementer.

2. **Refresh token** — Should the endpoint also return a refresh token?
   The spec mentions a `POST /refresh` endpoint elsewhere but does not
   explicitly say whether `/login` should pre-emptively return one.

## API reviewer contact

Agent `api-reviewer` is subscribed to `ticket:DEMO-001` and has authority
over token lifetime and refresh-token policy. Post clarification questions
there.

## Acceptance criteria

- `POST /login` returns `200 OK` with `{ "access_token": str, "expires_in": int }`.
- Invalid credentials return `401`.
- The implementation records its token-lifetime assumption in comments.
- If the API reviewer's answer differs from the assumption, the implementation
  is reconciled before the task is marked done.

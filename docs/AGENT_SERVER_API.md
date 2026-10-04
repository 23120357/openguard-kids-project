# Agent - Server API v1

Status: proposed contract. This document describes the target API; it does not
claim that every endpoint is implemented yet. The current scaffold remains
documented in [API.md](API.md).

The implemented Week-2 subset intentionally remains under `/api` and uses
HMAC-SHA256 for the loopback lab. See [WEEK2_F4.md](WEEK2_F4.md) for the exact
implemented behaviour; the `/api/v1` and Ed25519 material below is the production
target, not a claim about the current build.

The approved household, multi-parent, shared-device, and logical device identity
model is recorded in [HOUSEHOLD_DESIGN.md](HOUSEHOLD_DESIGN.md). That design
supersedes this contract's original one-device-one-child assumption and must be
applied when the v1 endpoints are implemented.

Development and production milestones for the household UI, platform admin,
agent, server, storage, and operations are defined in
[PLATFORM_STAGED_DESIGN.md](PLATFORM_STAGED_DESIGN.md).

## 1. Requirements traced from the assignment

The API must support these flows from the requirement document:

- an 8-character, single-use enrollment code that expires after 10 minutes;
- a device access token valid for 15 minutes and a rotating refresh token;
- a heartbeat every 60 seconds carrying status, used quota and current policy
  version;
- versioned policy download with an integrity signature;
- urgent commands delivered in under 5 seconds through WebSocket, with the
  heartbeat as a fallback;
- offline event buffering and idempotent batch upload after reconnection;
- child requests that are recorded and always receive a parent decision;
- deletion of the child's server data and the agent's local cache;
- TLS 1.2 or later, certificate pinning, device revocation and data minimisation.

The following are design decisions made by this project, rather than literal
instructions from the PDF:

- all new agent endpoints live under `/api/v1/agent`;
- Unix timestamps are UTC integer seconds, matching the current server;
- policies and commands use Ed25519 signatures instead of a shared HMAC key;
- restrictive controls fail open after a signed policy has been expired for 7
  days. The tray remains visible and explains that protection is inactive;
- event batches are atomic and use an `Idempotency-Key` HTTP header;
- a policy revision has both an increasing `version` and a unique `policy_id`.

## 2. Trust and transport

Production and lab-network deployments use HTTPS/WSS with TLS 1.2 or later.
Plain HTTP is allowed only for loopback development and automated tests.

The installed agent is provisioned with a SHA-256 SPKI pin for the server
certificate. It must reject a certificate whose chain is valid but whose pin is
not configured. Tokens are never placed in URLs or logs.

Authenticated requests use:

```http
Authorization: Bearer <access-token>
Content-Type: application/json
```

The access token is opaque, device-bound and valid for 15 minutes. The refresh
token is rotated on every successful refresh and stored on Windows with DPAPI in
an ACL-protected location. The server stores only token hashes. Revoking a
device invalidates both token types and closes its WebSocket.

The enrollment endpoint is unauthenticated because possession of the short-lived
code is its credential. Rate limiting is mandatory for enrollment and refresh.

## 3. Endpoint summary

| Method | Path | Purpose | Authentication |
|---|---|---|---|
| POST | `/api/v1/agent/enroll` | Consume pairing code and create device identity | Enrollment code |
| POST | `/api/v1/agent/auth/refresh` | Rotate access and refresh tokens | Refresh token in body |
| POST | `/api/v1/agent/heartbeat` | Report health and receive sync hints/queued commands | Device bearer token |
| GET | `/api/v1/agent/policy` | Download the latest signed policy | Device bearer token |
| POST | `/api/v1/agent/events/batches` | Upload one idempotent, atomic event batch | Device bearer token |
| POST | `/api/v1/agent/requests` | Record a child's request | Device bearer token |
| POST | `/api/v1/agent/commands/acks` | Acknowledge command execution | Device bearer token |
| WS | `/api/v1/agent/commands/ws` | Receive urgent commands and request decisions | Device bearer token |

The machine-readable HTTP contract is in
[openapi-agent-v1.yaml](openapi-agent-v1.yaml). OpenAPI cannot fully describe a
WebSocket exchange, so section 10 is authoritative for that stream.

## 4. Common rules

### 4.1 Headers

- Every request may include `X-Request-ID: <uuid>` for tracing. The server
  returns it or generates one.
- `POST /events/batches` requires `Idempotency-Key: <uuid>`.
- Secrets, full URLs, window titles, typed text and screenshots are forbidden in
  headers and bodies.
- Server responses include `Cache-Control: no-store` when they contain tokens,
  policy, commands or request decisions.

### 4.2 Error envelope

```json
{
  "error": {
    "code": "policy_not_modified",
    "message": "The agent already has the latest policy.",
    "request_id": "b79a6880-2cc3-45ff-aa9f-099c50f42d30",
    "retryable": false,
    "retry_after_sec": null
  }
}
```

Expected status codes are `400` malformed request, `401` expired/invalid token,
`403` revoked device, `404` unknown resource, `409` idempotency or state
conflict, `413` batch too large, `422` schema error, `429` rate limited and
`503` temporary server failure. A `401` causes one refresh-and-retry. A `403`
never causes an automatic enrollment attempt.

### 4.3 Retry behaviour

The agent retries `429` and `5xx` responses with exponential backoff and jitter,
honouring `Retry-After`. It retries a batch with the same idempotency key and
byte-equivalent body. It must not retry a non-idempotent request under a new key
unless it intentionally creates a new operation.

## 5. Enrollment and token rotation

The dashboard creates the code only after explicit parent consent is recorded in
the audit log. The agent sends a random installation identifier; hardware serial
numbers, Windows usernames and MAC addresses are not fingerprints.

```http
POST /api/v1/agent/enroll
```

```json
{
  "code": "7KMQ2PXR",
  "display_name": "May hoc cua An",
  "installation_id": "0f82f860-43db-43fc-a6c1-672328bb8172",
  "agent_version": "0.2.0"
}
```

```json
{
  "device_id": "8791dbaa-d66a-4a61-947d-ebda083be8b2",
  "child_id": "a10fb205-45d5-46b6-b0e2-4baf36805608",
  "access_token": "<opaque>",
  "refresh_token": "<opaque>",
  "token_type": "bearer",
  "expires_in": 900,
  "server_time": 1790910000,
  "policy_signing_keys": [
    {"kid": "policy-2026-01", "alg": "Ed25519", "public_key": "<base64url>"}
  ],
  "command_signing_keys": [
    {"kid": "command-2026-01", "alg": "Ed25519", "public_key": "<base64url>"}
  ]
}
```

The policy and command signing keys arrive over the already pinned TLS channel
and are stored with the agent configuration. Key rotation must overlap: a new
key is distributed before an object is signed only by that key.

Refresh rotates both secrets atomically:

```http
POST /api/v1/agent/auth/refresh
```

```json
{"device_id":"<uuid>","refresh_token":"<opaque>"}
```

Reusing the old refresh token returns `401`. Concurrent refresh attempts are
therefore serialized by the service.

## 6. Heartbeat

The Windows service sends a heartbeat every 60 seconds. Heartbeats do not carry
application or domain histories; those are event batches.

```json
{
  "sent_at": 1790910000,
  "policy_version": 12,
  "agent_version": "0.2.0",
  "tray_visible": true,
  "state": "active",
  "usage": {
    "local_date": "2026-10-02",
    "active_sec": 1620,
    "quota_sec": 5400,
    "remaining_sec": 3780
  },
  "outbox": {"pending_events": 24, "pending_requests": 1},
  "clock": {
    "wall_time": 1790910000,
    "monotonic_sec": 43321,
    "boot_id": "713319c6-7eef-425b-b3e8-79e5f13f0d86"
  }
}
```

`state` is one of `active`, `grace`, `locked`, `paused`, `policy_expired` or
`inert_no_tray`. `boot_id` is random for each boot and supports clock-tampering
analysis without exposing hardware identity.

```json
{
  "server_time": 1790910001,
  "heartbeat_after_sec": 60,
  "policy": {"latest_version": 13, "changed": true},
  "commands": []
}
```

The agent compares `server_time` with its wall and monotonic clocks. A material
backwards wall-clock jump creates an allowed `quota_warning` event; it never
adds time to the quota.

Queued commands in the response use exactly the same signed command envelope as
the WebSocket. This is the recovery path when WebSocket is unavailable.

## 7. Signed policy

```http
GET /api/v1/agent/policy?known_version=12
```

The server returns `304 Not Modified` when version 12 is current, otherwise:

```json
{
  "schema_version": 1,
  "policy_id": "aac847e6-a452-4a55-b1ac-27ef81ea08bf",
  "child_id": "a10fb205-45d5-46b6-b0e2-4baf36805608",
  "version": 13,
  "issued_at": 1790910000,
  "not_before": 1790910000,
  "expires_at": 1791514800,
  "payload": {
    "timezone": "Asia/Ho_Chi_Minh",
    "daily_quota": {"weekday_minutes": 90, "weekend_minutes": 120},
    "schedule": {
      "slot_minutes": 30,
      "days": [
        "000000000000111111111111111111111111111100000000",
        "000000000000111111111111111111111111111100000000",
        "000000000000111111111111111111111111111100000000",
        "000000000000111111111111111111111111111100000000",
        "000000000000111111111111111111111111111100000000",
        "000000000000111111111111111111111111111100000000",
        "000000000000111111111111111111111111111100000000"
      ]
    },
    "warnings_minutes": [10, 5, 1],
    "grace_sec": 60,
    "idle_after_sec": 300,
    "applications": [],
    "domains": [],
    "category_defaults": {},
    "safe_search": true,
    "permanent_allowlist": []
  },
  "integrity": {
    "alg": "Ed25519",
    "kid": "policy-2026-01",
    "signature": "<base64url>"
  }
}
```

`schedule.days` is Monday through Sunday. Each string contains exactly 48
characters; `1` permits a half-hour slot and `0` blocks it. Application rules
identify an executable by SHA-256 plus process name. Domain rules contain only a
normalized domain, an `include_subdomains` flag, an action, a category and a
child-readable reason code. Full URLs are invalid.

`permanent_allowlist` is additive. The agent also ships with a non-removable,
versioned safety baseline for the school portal, child-protection hotline and
operating-system emergency services required by the assignment. A downloaded
policy may add entries but cannot remove or override that baseline.

The signature covers the RFC 8785 canonical JSON representation of every
top-level field except `integrity`. Before atomically replacing its cache, the
agent verifies:

1. the signature and known `kid`;
2. the authenticated device belongs to `child_id`;
3. `schema_version` is supported;
4. `version` is greater than the cached version;
5. `not_before <= server-adjusted-now < expires_at`;
6. the permanent safety allowlist is present and valid.

If verification fails, the agent keeps the last valid policy and emits no
sensitive diagnostic data. After seven days beyond `expires_at`, restrictive
controls fail open, the tray displays `Chinh sach da het han`, and the service
continues reconnecting. This avoids indefinite enforcement of stale rules and
is the project's explicit answer to the PDF's fail-open/fail-closed decision.

## 8. Offline event batches

The event object has exactly the seven fields required by the PDF. No event ID,
URL, window title, keystroke, screenshot or arbitrary metadata may be added.

```json
{
  "events": [
    {
      "ts": 1790910000,
      "device_id": "8791dbaa-d66a-4a61-947d-ebda083be8b2",
      "child_id": "a10fb205-45d5-46b6-b0e2-4baf36805608",
      "type": "blocked_domain",
      "subject": "example.test",
      "duration_sec": 0,
      "policy_id": "aac847e6-a452-4a55-b1ac-27ef81ea08bf"
    }
  ]
}
```

Allowed `type` values are exactly:

`app_start`, `app_stop`, `domain_query`, `blocked_app`, `blocked_domain`,
`quota_warning`, `locked`, `unlock_request`, `override_granted`.

Rules:

- 1 to 500 events and at most 1 MiB uncompressed per batch;
- the authenticated device and child must match every event;
- `subject` is an application display name or registrable domain (eTLD+1), not a
  URL; server validation caps it at 253 characters. For system-level events
  (`quota_warning`, `locked`, `unlock_request`, `override_granted`), the reserved
  application display name is `OpenGuard Kids` so the required field still obeys
  the assignment's application-or-domain restriction;
- `duration_sec` is zero unless the event type represents a duration;
- the entire batch succeeds or fails;
- the server persists the idempotency key, request-body digest and response for
  at least 90 days. Reusing a key with different bytes returns `409`;
- the agent deletes local rows only after a successful response.

```json
{
  "batch_id": "d4874b17-2c8f-4865-a7f8-141a336702e8",
  "accepted": 1,
  "duplicate": false,
  "received_at": 1790910010
}
```

Server retention deletes event content after 90 days. Aggregate reports must not
retain recoverable event subjects beyond that period.

## 9. Child requests and parent response

Requests are separate resources, not overloaded event objects. This lets every
request have a durable status and response while preserving the seven-field
event schema.

```json
{
  "request_id": "629fdd19-9822-46df-9669-28e678867e4f",
  "created_at": 1790910000,
  "type": "extra_time",
  "details": {"requested_minutes": 15}
}
```

For a suspected false block, `type` is `review_block` and details contain only
`subject`, `subject_kind` (`app` or `domain`), `policy_id` and a fixed
`reason_code`. Free-form text is deliberately excluded to minimise children's
personal data. `request_id` is generated by the agent and makes retries
idempotent.

The server returns `202 Accepted` with `status: pending`. A parent decision is
delivered as a signed `request_resolved` command containing `request_id`,
`decision`, an optional `granted_minutes`, `decided_at` and a child-readable
`response_code`. The tray keeps the request visible until that command is
acknowledged.

The required dashboard counterparts are:

- `GET /api/v1/children/{child_id}/requests`;
- `POST /api/v1/requests/{request_id}/decision`.

They use the existing parent session, CSRF and ownership checks and are outside
the agent authentication boundary.

## 10. Urgent command WebSocket

The agent connects to:

```text
wss://<server>/api/v1/agent/commands/ws
```

The opening handshake carries the bearer token in the `Authorization` header,
never in the query string. After connection:

1. server sends `hello` with `server_time`, `heartbeat_after_sec` and latest
   policy version;
2. agent sends `ready` with its cached policy version;
3. server pushes signed commands;
4. agent sends an `ack` after durable receipt and another after execution;
5. both sides exchange WebSocket ping/pong; no application data is sent in ping.

Command envelope:

```json
{
  "type": "command",
  "command": {
    "command_id": "2a2e88f7-18dc-4205-bdeb-f0875a42ab18",
    "sequence": 104,
    "kind": "grant_extra_time",
    "issued_at": 1790910000,
    "expires_at": 1790910060,
    "payload": {"minutes": 15, "request_id": "<uuid>"},
    "integrity": {
      "alg": "Ed25519",
      "kid": "command-2026-01",
      "signature": "<base64url>"
    }
  }
}
```

Required kinds are `lock_now`, `unlock_now`, `grant_extra_time`,
`request_resolved` and `purge_local_data`. Commands are at-least-once: the agent
stores processed IDs and never executes the same ID twice. It rejects an expired,
out-of-order or invalidly signed command and acknowledges the rejection with a
stable result code. The server keeps delivering an unacknowledged command via
WebSocket and heartbeat until it expires or reaches a terminal acknowledgement.
`sequence` increases independently for each device. The signature covers the RFC
8785 canonical JSON form of every command field except `integrity`.

Acknowledgements can be sent on the socket or, after reconnect, to
`POST /api/v1/agent/commands/acks`:

```json
{
  "acks": [
    {
      "command_id": "2a2e88f7-18dc-4205-bdeb-f0875a42ab18",
      "stage": "executed",
      "at": 1790910002,
      "result": "ok"
    }
  ]
}
```

The acceptance target is p95 under 5 seconds from committed parent action to
`executed` acknowledgement on an online agent.

## 11. Data deletion

Distributed deletion cannot be truly atomic while a device is offline. The API
therefore uses a visible deletion workflow rather than claiming immediate global
success:

1. parent requests deletion; the server deletes server-side event/report data,
   creates a deletion record and queues `purge_local_data` for every device;
2. each agent deletes its event queue, report cache and request history but keeps
   only the minimum enrollment credentials needed to receive revocation;
3. each agent acknowledges the command;
4. the dashboard shows `pending_device_cleanup` until all active devices confirm,
   then `completed`. A revoked or irrecoverably lost device is shown explicitly.

The required dashboard operation is
`DELETE /api/v1/children/{child_id}/data`. It returns `202` and a `deletion_id`.

## 12. Privacy and security validation

- The server derives device ownership from the bearer token and rejects body
  identifiers that do not match; it never trusts `child_id` alone.
- Agent endpoints do not accept parent cookies, and dashboard endpoints do not
  accept device bearer tokens.
- Policy and command signing keys are separate from TLS keys.
- The tray's presence is reported. If it cannot remain visible, the service
  becomes `inert_no_tray`, stops enforcement and reports that state.
- Event and request schemas reject unknown fields (`additionalProperties: false`).
- Audit entries record enrollment consent, policy changes, command creation,
  parent request decisions, revocation and deletion: actor, time, direct client
  IP, old value and new value.
- Server logs redact `Authorization`, refresh tokens, enrollment codes and event
  subjects.

## 13. Compatibility and implementation order

The current scaffold implements unversioned `/api/enroll`,
`/api/auth/device/refresh`, `/api/heartbeat` and `/api/policy`. During migration:

1. add database migrations for immutable policy revisions, signing keys, event
   batches, events, requests, commands, acknowledgements and deletion records;
2. implement `/api/v1/agent` without removing the current routes;
3. make the service use v1 behind a feature flag and test enrollment, retry and
   offline replay;
4. switch the simulator and tests to v1;
5. remove the old routes only after one documented compatibility release.

Minimum acceptance tests for the contract are:

- expired/reused enrollment code and explicit consent enforcement;
- access expiry, refresh rotation, revocation and WebSocket close;
- policy signature, version rollback, expiry and wrong-child rejection;
- heartbeat server-time comparison and 60-second policy propagation;
- duplicate event batch returns the original response without duplicate rows;
- same idempotency key with changed body returns `409`;
- offline events survive restart and are deleted only after server acceptance;
- urgent command delivery, duplicate delivery and acknowledgement under 5 seconds;
- request creation, parent decision, child-visible response and audit entry;
- data deletion while online and pending cleanup while offline;
- attempts to send full URLs, extra event fields or another device's IDs fail.

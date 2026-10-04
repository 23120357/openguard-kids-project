# Platform Views and Staged Component Design

Status: approved design artifact. This document defines how OpenGuard Kids
evolves from the current coursework scaffold into a production-oriented system.
It describes intended behavior and milestones; it does not mark unimplemented
features as complete.

Related design documents:

- [SYSTEM_DIAGRAMS.md](SYSTEM_DIAGRAMS.md) visualizes the D4 development and P4
  production architectures and their trust boundaries.
- [HOUSEHOLD_DESIGN.md](HOUSEHOLD_DESIGN.md) defines ownership, policy
  authority, child profiles, and logical device identity.
- [AGENT_SERVER_API.md](AGENT_SERVER_API.md) defines the proposed Agent-Server
  protocol.
- [LOCAL_IPC.md](LOCAL_IPC.md) defines the Service-Tray named-pipe boundary.

## 1. Product surfaces

OpenGuard Kids has four deliberately separate surfaces:

| Surface | Audience | Purpose |
|---|---|---|
| Household workspace | Household owners and guardians | Manage children, policies, devices, requests, reports, and household audit |
| Household administration | Household owner | Manage invitations, members, ownership, exports, deletion, and household settings |
| Child experience | Child using an assigned Windows session | Select a profile in the demo, view time/status/reports, submit requests, and see understandable explanations |
| Platform administration | OpenGuard Kids operators | Operate and test the service without sharing parent identities or sessions |

The household is a data and authorization boundary, not a login account. Every
parent and every platform operator has an individual identity.

## 2. Milestone map

Milestones are sequential unless explicitly noted. A production milestone does
not silently redefine the development behavior; changes must be implemented and
tested as migrations.

| Milestone | Outcome | Exit gate |
|---|---|---|
| D0 - Current scaffold | One parent owns children directly; basic policy sync; Service-Tray skeleton | Existing tests pass and current limitations remain documented |
| D1 - Household foundation | Household membership, child ownership migration, immutable policy revisions, role checks | Two distinct parents can share a household without cross-household access |
| D2 - Household and child experience | Full household navigation, owner settings, device-child binding, shared-account child PIN demo | Complete household flow works on desktop/mobile and two children can share one test PC |
| D3 - Development administration | Separate admin identity and development-only CRUD console | Operators can maintain synthetic business data without seeing secrets or altering audit history |
| D4 - Integrated development demo | Agent API v1, requests, events, reports, commands, retention, and end-to-end demo hardening | Automated acceptance suite passes and no real child data is required for the demo |
| P1 - Production data and identity | PostgreSQL, durable migrations/backups, hardened authentication, production authorization | Restore test, tenancy test, and authentication security review pass |
| P2 - Production Windows agent | Separate Windows accounts, SID mapping, DPAPI device identity, signed policy/commands, installer hardening | Clean Windows 10/11 installation and security/bypass tests pass |
| P3 - Production privacy and operations | Metadata-only platform console, owner-approved support grants, monitoring, retention and incident controls | Privacy review, support-access review, and operational alert tests pass |
| P4 - Production release gate | Capacity, recovery, security, legal, and deployment evidence completed | Release checklist is signed off; development-full administration cannot start in production |

## 3. Component evolution

### 3.1 Parent identity and household membership

**Development - D1**

- Replace direct `Parent -> Child` ownership with `User`, `Household`, and
  `HouseholdMember`.
- Use roles `owner` and `guardian`. Both manage every child and have equal policy
  authority; only the owner manages membership and ownership transfer.
- Allow one user to belong to multiple households and expose a household
  switcher.
- Use existing Argon2id login, 12-hour cookie session, CSRF protection, and
  lockout behavior.
- Use single-use household invitations that expire after 24 hours.

**Production - P1**

- Keep individual identities and memberships; never introduce shared household
  credentials.
- Require reauthentication for ownership transfer, deletion, export, and member
  removal.
- Add verified-email recovery and session/device management.
- Require MFA for platform administrators; support optional parent MFA and
  step-up MFA for sensitive owner actions.
- Persist rate limits and session revocation so they work across server
  instances.

### 3.2 Household workspace

**Development - D2**

Serve a responsive Vietnamese household application under
`/app/h/{household_id}` using FastAPI/Jinja2 and small vanilla JavaScript
modules. No Node build pipeline is required.

Navigation and views:

- **Overview:** child cards, remaining quota per device, device status, pending
  requests, policy sync warnings, and recent changes.
- **Children:** create and rename child profiles; owner-only permanent deletion.
- **Child detail:** Today, Policy, Schedule, Applications/Websites, Requests,
  Reports, Devices, and Audit tabs.
- **Devices:** online status, agent/tray health, last heartbeat, agent version,
  bound children, cached policy versions, pairing, revocation, and owner-only
  permanent record removal.
- **Requests:** approve or deny extra-time and false-block requests and show
  delivery acknowledgement.
- **Reports:** per-child and per-device day/week summaries, top applications and
  domains, block counts, and test-data export.
- **Audit:** actor, child, action, and date filters with readable old/new policy
  values.
- **Members:** owner-only invitation, removal, pending invite, and ownership
  transfer.
- **Settings:** household name, timezone, export, child-data deletion status, and
  danger-zone operations.

The header contains household switching, notifications, current identity, role,
and logout. Navigation collapses for mobile and remains keyboard accessible.

**Production - P1/P3**

- Preserve the same information architecture so production is an upgrade, not a
  second product.
- Add durable notifications, verified export delivery, deletion progress across
  offline devices, session management, and accessible localization.
- Enforce 90-day activity retention in the query layer and exports.
- Provide the child-facing form of reports and audit without exposing IP
  addresses, parent security state, or operator information.
- Apply content-security, dependency-integrity, and accessibility release gates.

### 3.3 Household policy and conflict handling

**Development - D1/D2**

- Keep one effective policy per child, shared by all guardians.
- Store an immutable `PolicyRevision` and a `PolicyHead` pointing to the current
  version.
- Require `expected_version` on writes. The first update commits; another write
  from the old version returns `409`.
- Show a UI comparison of the intervening revision. The guardian must explicitly
  reload, merge, and submit; there is no silent merge or unanimous approval.
- Undo creates a new revision and audit entry.
- Start with weekday/weekend quotas, then add the 7x48 schedule and application,
  domain, category, SafeSearch, warning, and grace settings by D4.

**Production - P1/P2**

- Preserve optimistic concurrency and immutable revisions.
- Sign complete policies using managed Ed25519 keys with rotation and `kid`.
- Validate schema, signature, child binding, monotonic version, time window, and
  mandatory safety allowlist before the agent activates a revision.
- Keep the approved fail-open behavior after seven days beyond policy expiry,
  with visible child and parent warnings.

### 3.4 Device identity and enrollment

**Development - D2/D4**

- Treat a device as one logical agent installation, not physical hardware.
- Generate UUIDv4 `installation_id` and an Ed25519 key pair during enrollment.
- Define the server fingerprint as SHA-256 of the public key.
- Never derive identity from MAC address, disk serial, MachineGuid, or Windows
  username.
- Enrollment code creation records parent consent, household, and permitted
  child IDs. The code expires after 10 minutes and is single-use.
- Reinstallation creates a new device record; the previous record remains until
  revoked.

**Production - P2**

- Store the private key using DPAPI LocalMachine and restrict ProgramData ACLs to
  SYSTEM/Administrators.
- Require proof of possession during enrollment and credential refresh.
- Add signed installer identity, upgrade preservation, Service Recovery Options,
  secure uninstall, and reliable old-device revocation.
- Verify that copied identity material cannot be used on another computer.

### 3.5 Child selection and Windows sessions

**Development - D2**

- Support one shared Windows account for the demonstration.
- A parent explicitly assigns a subset of household children to the device and
  creates a local six-digit PIN for each binding.
- On Windows login, Tray shows only assigned profiles. The Service validates the
  PIN over the named pipe and activates the selected binding.
- Store only salted Argon2id PIN hashes and persistent retry counters in the
  Service-owned local database. PINs never reach the server or logs.
- Clear the active child at logout. While no child is selected, remain visibly
  `awaiting_profile`, collect no activity, and enforce no child policy.
- Document that this cooperative flow is a demo convenience, not a robust
  security boundary.

**Production - P2**

- Require a separate non-administrator Windows account for each child.
- Map the local Windows SID to `DeviceChildBinding`; never upload the raw SID.
- Select the child automatically from the active Windows session.
- Unknown Windows users receive visible unassigned status and no monitoring or
  child enforcement, preventing accidental adult surveillance.
- Restrict enforcement to the foreground console session and document behavior
  for fast-user switching and unsupported remote sessions.

### 3.6 Windows Service, Tray UI, and local IPC

**Development - D0/D2/D4**

- Keep the Service under LocalSystem and Tray in the interactive user session.
- Extend named-pipe v1 with assigned-profile listing, PIN verification, active
  binding, status, child requests, and local report summaries.
- Reject unknown operations and fields; keep the pipe local-only with explicit
  ACL and remote-client rejection.
- Tray must remain visible and explain connection, inactive-policy, blocked, and
  awaiting-profile states.
- At D4, add local cache and durable outboxes for policy, events, requests, and
  command acknowledgements.

**Production - P2**

- Add SCM recovery, bounded retries, local database migrations, DPAPI secrets,
  tamper-resistant ACLs, and signed binaries.
- Stop enforcement and become visibly inert if Tray presence cannot be
  maintained, preserving the anti-stalkerware rule.
- Measure Service/Tray recovery, idle usage, clock changes, session changes, and
  failure behavior on supported Windows versions.

### 3.7 Agent-Server API and command delivery

**Development - D4**

- Implement `/api/v1/agent` enrollment, refresh, heartbeat, policy, event batch,
  request, command acknowledgement, and WebSocket endpoints.
- Bind one device credential to a household and validate every child operation
  through `DeviceChildBinding`.
- Heartbeat reports assigned policy versions and the active binding.
- Deliver signed commands by WebSocket with heartbeat fallback and at-least-once
  semantics.
- Keep event objects to the required seven fields and place idempotency outside
  the event body.
- Use HTTP on loopback only for tests; use lab HTTPS when traffic leaves the
  machine.

**Production - P2/P3**

- Require TLS 1.2+ and SPKI certificate pinning for HTTPS/WSS.
- Use durable command/event queues suitable for multiple server processes and
  preserve per-device command ordering.
- Add signing-key rotation, persistent distributed rate limits, bounded payload
  sizes, replay protection, and operational latency metrics.
- Meet p95 under five seconds for urgent commands to an online agent and policy
  propagation within 60 seconds.

### 3.8 Activity, requests, reports, and retention

**Development - D4**

- Queue events locally while offline and upload atomic batches with an
  idempotency key.
- Store only application names, registrable domains, durations, timestamps, and
  required identifiers; never store full URLs, window titles, typed text,
  messages, files, or screenshots.
- Provide request state from submission through parent decision and agent
  acknowledgement.
- Aggregate reports by child and device because quota consumption is per-device.
- Run a demonstrable 90-day cleanup job and distributed child-data deletion
  workflow.

**Production - P1/P3**

- Run retention and deletion as durable scheduled jobs with retry, progress, and
  alerts.
- Prevent aggregate tables and exports from retaining recoverable subjects past
  90 days.
- Encrypt sensitive stored fields with managed keys and test key rotation.
- Provide verifiable export/deletion receipts without retaining deleted child
  activity.

### 3.9 Platform administration

**Development - D3/D4**

- Use distinct `AdminUser`, `AdminSession`, `/admin/login`, `/admin/*`, and
  `ogk_admin_session`; parent sessions never authorize admin routes.
- Enable full CRUD for business records only when
  `OGK_ENV=development` and `OGK_ADMIN_MODE=development_full`.
- Provide Operations, Households, Accounts, Children, Devices, Policies,
  Requests/Commands, Activity/Reports, System Audit, and System Settings views.
- Permit management of synthetic household data, but never reveal password
  hashes, token values, PINs, SIDs, private keys, or other secrets.
- Do not permit parent impersonation or alteration/deletion of audit records.
- Require password re-entry and a typed target name for destructive actions.
- Record every admin mutation with admin identity, reason, IP, time, resource,
  and old/new values in immutable `AdminAudit`.
- Display a permanent warning that development admins can inspect child test
  data and that real child data must not be used.

**Production - P3**

- Remove general business-record CRUD from the operator console.
- Expose metadata and operational health by default: counts, delivery status,
  versions, storage, retention jobs, failures, and security events.
- Require an operator to request a scoped support session with ticket/reason;
  require household-owner approval; cap it at 30 minutes; make it visible and
  revocable; audit every read and write.
- Require administrator MFA and reauthentication for security actions.
- Fail application startup when `development_full` is configured outside the
  development environment.

### 3.10 Server data and migrations

**Development - D1/D4**

- Add an Alembic baseline before altering the current `create_all` schema.
- Continue using SQLite WAL for the single-process coursework environment.
- Migrate each existing parent into an owner membership and generated household,
  preserve child IDs, create device-child bindings, and create policy revision 1.
- Keep legacy API routes for one compatibility milestone while the UI and agent
  move to v1.

**Production - P1**

- Move server persistence to PostgreSQL through SQLAlchemy/Alembic migrations.
- Add transaction-level tenancy checks, indexes, backups, point-in-time recovery,
  migration rollback/runbooks, and restore drills.
- Use a durable shared store for sessions, rate limits, command notification, and
  background-job coordination.
- Remove legacy routes after compatibility telemetry confirms no remaining
  clients.

### 3.11 Deployment and observability

**Development - D0-D4**

- Run FastAPI locally or on a controlled lab LAN with SQLite, synthetic data,
  console logs, install/cleanup scripts, and visible development banners.
- Keep one server process where in-memory components are explicitly documented.
- Provide seeded household, guardian, child, device, request, event, and admin
  examples for repeatable demonstrations.

**Production - P3/P4**

- Use HTTPS/WSS behind a hardened reverse proxy, managed secrets, PostgreSQL,
  durable workers, backups, and separate staging/production configuration.
- Emit structured logs and metrics while redacting secrets and child activity
  subjects.
- Alert on authentication abuse, heartbeat loss, command delay, retention
  failure, deletion failure, storage growth, signing-key expiry, and backup
  failure.
- Publish Windows installer upgrade/rollback instructions and server disaster
  recovery procedures.

## 4. View-level authorization matrix

| Capability | Guardian | Household owner | Development platform admin | Production platform admin | Child view |
|---|---:|---:|---:|---:|---:|
| View/manage household children | Yes | Yes | Yes, test data | No by default | Own profile only |
| Edit child policy | Yes | Yes | Yes, audited revision | Support grant only | No |
| Resolve child requests | Yes | Yes | Yes, test data | Support grant only | Submit/view own |
| Pair/revoke device | Yes | Yes | Yes | Security metadata/revocation | No |
| Invite/remove guardians | No | Yes | Yes, test data | No | No |
| Transfer household ownership | No | Yes | Yes, test data | No | No |
| Delete/export child data | No | Yes | Yes, test data | Support/operations only | No |
| View child activity subjects | Yes | Yes | Yes, development warning | Support grant only | Own friendly report |
| View operational metadata | Household only | Household only | All | All | No |
| View or alter audit history | View household | View household | View all; never alter | View all; never alter | Sanitized own history |
| Access credentials/private keys | No | No | No | No | No |

## 5. Acceptance gates by stage

### Development release D4

- Parent A and Parent B use separate accounts in the same household and produce
  distinct audit entries.
- Cross-household child, policy, device, report, request, and audit access fails
  at the query layer.
- Concurrent policy edits produce one commit and one visible `409` resolution
  flow.
- One shared Windows test account can select two assigned child profiles using
  local PINs; no PIN reaches the server.
- Device and child identifiers cannot be substituted in Agent API requests.
- Offline event retry does not duplicate data; urgent command acknowledgement
  is demonstrated.
- Development platform admin CRUD works only behind both environment gates;
  secrets remain redacted and audits remain immutable.
- Household and admin views pass mobile, keyboard, and basic accessibility tests.
- All work uses synthetic child activity.

### Production release P4

- Parent and administrator authentication, MFA, recovery, revocation, CSRF,
  rate limiting, and tenancy protections pass security review.
- Windows SID mapping, DPAPI identity, certificate pinning, policy/command
  signature verification, and Service recovery pass clean-machine tests.
- PostgreSQL backup restore, migration rollback, retention, deletion, and key
  rotation are demonstrated.
- Production operators cannot access child data without an owner-approved,
  scoped, expiring, fully audited support grant.
- `development_full` configuration causes startup failure in production.
- Performance, command latency, DNS impact, resource usage, incident response,
  privacy documentation, and legal-use documentation are complete.

## 6. Fixed design decisions

- No shared parent or platform-admin credentials.
- One effective policy per child; no unanimous parent approval requirement.
- Equal policy authority for owner and guardians; membership administration is
  owner-only.
- All guardians may manage all children in their household.
- Quota consumption is independent per device.
- Device identity is a logical installation identity, not hardware tracking.
- Shared-account PIN selection exists only for the development demonstration;
  separate Windows accounts are the production security model.
- Development platform administrators have business-data CRUD but no secret,
  impersonation, or audit-mutation capability.
- Production platform administrators are metadata-only unless an owner approves
  a scoped temporary support grant.
- OpenGuard Kids never implements hidden monitoring or collects prohibited
  content.

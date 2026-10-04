# Household, Parent, Child, and Device Architecture

Status: approved design plan. This document describes the target architecture;
it does not claim that the model, APIs, or migration have been implemented.

The household and platform views, component-by-component development/production
behavior, and milestone gates are specified in
[PLATFORM_STAGED_DESIGN.md](PLATFORM_STAGED_DESIGN.md).

## Summary

Use a household as a data container, not as a shared login. Every parent gets an
individual account so authentication, consent, policy changes, and audit history
identify the actual person.

- A household has many parent accounts, children, and devices.
- All guardians in the household can manage all children.
- Each child has exactly one effective policy, shared across parents.
- Parents have equal policy authority; policy changes do not require unanimous
  approval.
- Quotas are enforced separately for each device.
- A device identity represents one agent installation, not permanent physical
  hardware.
- The shared-Windows-account child PIN flow is supported for the demo; separate
  Windows accounts are the production target.

## Identity and data model

Introduce these relationships:

- `User`: individual parent login, password, lockout state, and sessions.
- `Household`: tenant boundary containing children and devices.
- `HouseholdMember`: links users to households with `owner` or `guardian` role.
  Both roles have equal policy-editing authority. The owner alone manages
  invitations, membership removal, and ownership transfer.
- `Child`: belongs to one household instead of one parent.
- `Device`: belongs to one household and represents an enrolled agent
  installation.
- `DeviceChildBinding`: explicitly permits a device to be used by a child. Do
  not automatically expose every household child on every device.
- `PolicyHead`: stores the child's current policy version.
- `PolicyRevision`: immutable policy revisions containing author, version,
  timestamp, and policy body.
- `Audit`: records the real user account, household, child, action, IP,
  timestamp, old value, and new value.

A parent may belong to multiple households through separate memberships.
Child-view access remains read-only and child-specific rather than granting
household-wide parent permissions.

Migrate the current schema by creating one household for each existing parent,
making that parent the owner, moving their children into the household, creating
one binding for every existing device-child relationship, and turning each
existing policy into revision 1.

## Policy authority and conflict resolution

Do not maintain separate simultaneously effective policies for different
parents. An agent needs one deterministic policy for each child.

Policy updates use optimistic concurrency:

1. Parent loads policy version `N`.
2. Update request includes `expected_version: N`.
3. The first valid transaction creates revision `N+1`.
4. A concurrent update based on version `N` receives `409 Conflict`.
5. The response includes the current version and fields changed since version
   `N`.
6. The second parent reviews and explicitly reapplies or merges their changes.

There is no automatic merge, silent last-write-wins, or unanimous approval
requirement. Undoing a change creates another audited revision instead of
deleting history. Other guardians should receive a dashboard notification when
a policy changes.

Sensitive household operations such as removing a guardian, deleting a child,
or transferring ownership require password re-entry and are owner-only.
Ordinary policy edits and urgent child commands remain available to every
guardian.

## Device and child login design

### Demo: shared Windows account

At device enrollment, a parent chooses which household children may use that
device and creates a local six-digit PIN for each assigned child.

On every Windows login:

1. Tray UI displays only children assigned to the device.
2. Child selects their profile and enters its PIN.
3. The Windows service validates the PIN through the named pipe.
4. The service activates that child's binding, policy, event attribution, and
   per-device quota.
5. Profile selection is cleared at Windows logout.

PIN hashes and retry counters stay in the service's ACL-protected local database
and are never uploaded or logged. Use Argon2id, a unique salt, and persistent
rate limiting. The tray must send an opaque binding ID rather than an arbitrary
`child_id`.

While no profile is selected, the agent remains visibly in `awaiting_profile`,
collects no activity data, and applies no child policy. Document that this demo
flow is cooperative and can be bypassed; it is not the production security
boundary.

### Production target: separate Windows accounts

Map each non-administrator Windows user SID locally to one
`DeviceChildBinding`. The raw SID never leaves the device. The service
automatically selects the child when that Windows session becomes active.

Unknown Windows accounts receive no monitoring or child enforcement and show a
visible unassigned status. Children cannot create another Windows account
because they are not administrators. This avoids monitoring adult users and
prevents selecting a sibling's more permissive profile.

## Device identity and API changes

Generate device identity during agent installation:

- random UUIDv4 `installation_id`;
- Ed25519 device key pair;
- private key protected using DPAPI LocalMachine and an ACL limited to
  SYSTEM/Administrators;
- server-side fingerprint defined as SHA-256 of the device public key.

Do not use MAC addresses, disk serials, Windows MachineGuid, or other hardware
identifiers. Software updates retain the identity; reinstalling or losing
ProgramData creates a new logical device. The old device remains visible until a
parent revokes it. Copying identity files to another machine fails because DPAPI
cannot decrypt the private key.

Update public APIs accordingly:

- Household endpoints create households, issue single-use 24-hour invitations,
  accept invitations, and manage members.
- Child and policy endpoints become household-scoped and enforce membership at
  query level.
- Enrollment-code creation accepts `household_id`, permitted `child_ids`, and
  explicit consent.
- Agent enrollment sends `installation_id`, device public key, and proof of
  private-key possession.
- Device tokens authorize only children present in `DeviceChildBinding`.
- Heartbeat reports the active child binding and known policy versions for
  assigned children.
- Policy download identifies the requested child; the server verifies that the
  device is assigned to that child.
- Events containing a child not assigned to the authenticated device are
  rejected.
- Commands include `device_id` and optional `child_id`; child-scoped commands
  execute only for that child's active session.
- Daily usage counters and quota enforcement are keyed by
  `(device_id, child_id, local_date)`, so each device receives the full quota
  independently.

Update the existing Agent-Server design and OpenAPI contract to replace the
current one-device-one-child authentication assumption while retaining signed
policies, idempotent event batches, token rotation, and command acknowledgements.

## Test and acceptance plan

- Two parents authenticate separately and produce distinguishable audit records.
- Guardians can manage every child in their household but cannot access another
  household.
- Concurrent updates from the same policy version produce one success and one
  `409`; no data is silently overwritten.
- Owner-only membership and deletion operations reject ordinary guardians.
- A device can access only explicitly assigned children and policies.
- Child PINs never appear in server requests, logs, or parent APIs.
- Wrong PINs are rate-limited; successful selection activates the correct local
  binding.
- Logout clears the selected child; no-selection state records no child
  activity.
- Device identity survives upgrades, changes after reinstall, and cannot be
  restored on another machine through copied DPAPI data.
- Events and commands with mismatched device-child bindings are rejected.
- The same child receives an independent quota on each assigned device.
- Migration preserves existing parents, children, devices, policies, and audit
  history.
- Existing enrollment, token, privacy, named-pipe, and service tests continue to
  pass.

## Chosen assumptions

- Parent credentials are never shared.
- Equal guardian authority applies to child policies, not household membership
  administration.
- All guardians may manage all children in their household.
- A policy is child-scoped and applies across that child's assigned devices;
  usage quota consumption remains per-device.
- The demo PIN identifies a child profile but is not presented as a strong
  security boundary.
- Reinstallation creates a new device identity and requires enrollment again.

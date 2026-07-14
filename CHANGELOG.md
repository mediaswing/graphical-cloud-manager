# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

On each tagged release (`vX.Y.Z`), the CI workflow publishes the matching
section below as the GitHub Release notes.

## [Unreleased]

## [0.7.0] - 2026-07-14

### Added
- Google Workspace administration, signed into independently via a new
  "Google Workspace" menu (its own Settings/Sign in/Sign out, separate from
  the Microsoft "Tenant" menu):
  - Users: list/search, create, edit, suspend/unsuspend, reset password,
    delete.
  - Groups: list/search, create, delete, and a membership panel (add/remove
    members by email).
  - Devices: mobile device inventory with approve/block/remote wipe/unenroll.
  - Mailbox admin: vacation responder, auto-forwarding (including Google's
    required forwarding-address verification step), and delegates. This
    needs a separate service-account credential with domain-wide delegation,
    configured in Google Workspace > Settings, since mailbox actions can't
    use the same interactive per-admin sign-in the other Google pages do.
  - Sign-in logs and an Admin audit log, both read from the Admin SDK
    Reports API.
- Application-wide error logging: a local rotating log file (Help > Open
  Error Log) now captures exceptions that weren't specifically handled
  elsewhere -- both on the main thread and inside background `@asyncSlot`
  tasks -- instead of a background failure silently vanishing. Background
  failures also show a notification dialog.

## [0.6.2] - 2026-07-12

### Fixed
- Users/Groups/Devices search: a term containing a literal `"` broke the
  Graph `$search` query instead of being escaped.
- Graph throttling (429) now surfaces as a clear "try again" message
  (including the `Retry-After` delay when Graph provides one) instead of a
  raw error body.
- `list_subscribed_skus` and the forwarding-rule lookup now page through
  every result instead of silently stopping at the first page.
- The local audit log rewrote its entire file on every single write once
  past the 5,000-entry cap, instead of just occasionally; it's now batched.
- The impact-preview dialog's "not all shown" caveat was only applied to
  the group-memberships line, not administrative roles -- both come from
  the same capped lookup, so a truncated page could hide an admin role
  just as easily as a group.
- Users/Groups/Devices: a slower, broader search or a stale member-list
  fetch could land after a faster, more recent one and silently overwrite
  it; refreshes now discard results that have been superseded.
- Deleting or disabling a device showed only a bare confirmation with no
  compliance/activity context (unlike the equivalent Users flow), and
  Disable had no confirmation step at all.
- Bulk enable/disable/delete (Users and Devices) aborted the whole batch on
  the first row that failed, silently skipping the rest of the selection;
  every row is now attempted, and the result reports exactly what
  succeeded and what didn't.
- Bulk import: a failed tenant-validation pass showed its error for a
  moment before the very next lines unconditionally overwrote it; the
  upfront SKU/group lookup in `execute()` could raise uncaught, leaving the
  UI stuck on "Running import..." with no explanation; and `execute()` no
  longer re-fetches the same SKU/group lists `validate_against_tenant()`
  just fetched for the same batch.
- Intune page: the CSV export's "User" column was hand-duplicated from the
  table's formatting and rendered differently for missing/partial user
  info (e.g. `()` instead of the table's `(none)`).
- Exchange forwarding: an external-domain warning used a naive
  string comparison instead of the tenant's actual verified domains, so
  forwarding between two of the tenant's own domains (e.g.
  `contoso.com` and `contoso.onmicrosoft.com`) was wrongly flagged as
  leaving the organization.
- A second concurrent sign-in attempt (while the first's interactive
  browser flow was still open) could race to assign the active auth
  session; the Sign in action is now disabled for the duration of one
  attempt.
- Sign-out no longer leaves the UI in a torn "still connected" state if
  clearing the persisted token cache fails for a reason beyond "nothing to
  delete".

## [0.6.1] - 2026-07-12

### Fixed
- **Windows self-update silently failed to install**: the updater's log file
  lived inside the install folder it was about to rename aside, so the move
  that placed the new build was skipped entirely once that folder no longer
  existed under its old name — leaving the old build renamed to `.bak` and
  nothing in its place. The log now lives outside the install folder, and
  the update script checks each step and aborts cleanly (leaving the `.bak`
  intact) instead of silently continuing.
- The startup update check and the Help > Check for Updates action could
  run concurrently with nothing to stop it, so two self-updates could race
  to replace the same install directory; a check now refuses to start a
  second one while one is already in progress.
- The update-progress dialog could be dismissed via Escape or the window's
  close button without actually stopping the in-flight update, misleading
  the user into thinking they'd cancelled something that was still running
  in the background (there is no safe way to cancel mid-replace, so the
  dialog now refuses to close).
- A manual "Check for Updates..." could silently do nothing if the check
  raised an unexpected error; it's now caught and reported.
- `parse_version` mis-parsed pre-release tags like `1.2.3-rc1` as `1.2.31`
  instead of `1.2.3`.
- The update-download step now rejects zip entries that would extract
  outside the target folder, and the macOS `.app` bundle path is resolved
  by walking up to the nearest `.app` ancestor instead of a fragile string
  split (which could pick the wrong directory on an unusual install path).
- Every Graph API call was silently redeeming a fresh access token over the
  network instead of reusing the one cached at sign-in (a scope mismatch
  between the two), and that MSAL call ran synchronously on the UI thread --
  freezing the whole app for the round trip on every single request, and
  for as long as an interactive re-sign-in took on a cache miss. Token
  acquisition is now properly asynchronous and reuses the same scopes sign-in
  cached the token under.

## [0.6.0] - 2026-07-12

### Added
- **Auto-update**: the app now checks GitHub Releases for a newer version a
  couple of seconds after startup, and offers a **Check for Updates...** item
  in a new Help menu. When a newer build is available, confirming downloads
  and installs it in place before relaunching (built/frozen copies only;
  running from source instead opens the release page in your browser).

## [0.5.0] - 2026-07-07

### Added
- **Sync with Intune**: right-clicking a device on the Devices page now
  offers a **Sync with Intune** action, asking Intune to check the device in
  now. This is the first Intune remote action implemented -- deliberately
  the least destructive one (fully reversible, no data loss), so it uses a
  plain Yes/No confirmation rather than the impact-preview framework used
  for delete/wipe-class actions. Offered from the Devices page (shown on
  every tenant) rather than the Intune page (only shown when Intune is
  licensed), so a tenant without Intune gets a clear "Intune not available"
  message instead of the action being silently absent. Wipe, retire, and
  restart remain out of scope.

## [0.4.1] - 2026-07-07

### Fixed
- **Exchange forwarding warning**: the confirmation dialog for setting up
  mail forwarding to an external address was missing your own tenant domain
  from its warning text due to a broken string (a missing `f`-prefix left
  the placeholder unsubstituted). The warning now correctly names both the
  external domain and your own, so this safety confirmation reads as
  intended.

## [0.4.0] - 2026-07-07

### Added
- **CSV export**: every list page (Users, Groups, Devices, Licensing,
  Roles, Sign-in logs, Intune, Audit log) has an `Export CSV...` button.
  Runs off the UI thread so exporting a large tenant's worth of data never
  freezes the window; opens a native, accessible save dialog.
- **Local audit log**: every write action this app performs (create/edit/
  delete/enable/disable a user, group membership changes, license changes,
  role assignment changes, bulk import rows, mailbox rule changes, etc.) is
  now recorded locally with actor, timestamp, action, target, success/
  failure, and before/after state where relevant. A new **Audit log** page
  lets you filter, search, and export it to CSV. This is a convenience log
  for whoever is running this app -- it does not replace Entra/Intune/
  Exchange's own server-side audit logs, and passwords/secrets are never
  written to it (e.g. a password reset logs that a reset happened, never
  the new password).
- **Bulk user import from CSV**: a new **Bulk import** page reads a CSV
  file (template: `docs/bulk_import_template.csv`), validates every row up
  front (required columns, UPN format, duplicate UPNs, existing-user
  check), shows a preview that clearly separates blocking errors from
  non-blocking warnings, then runs with bounded concurrency so one row's
  failure never stops the others. Every row's outcome is shown and logged
  -- nothing fails silently.
- **Group-based licensing**: the Licensing page now has a group-licensing
  panel alongside the existing per-user one -- assign/remove a license at
  the group level, with Microsoft's asynchronous processing state shown
  explicitly rather than implying instant effect. The per-user panel now
  also distinguishes licenses assigned directly from ones inherited
  through a group.
- **Dynamic group membership rule editor**: Groups can now view and edit a
  dynamic membership rule, via a raw text editor pre-filled with the
  existing rule, a guided builder for common single-condition rules, a
  preview, and client-side syntax validation (explicitly not a guarantee
  Entra will accept the rule -- only Entra fully validates rule semantics).
- **Intune device inventory** (read-only): a real Intune page listing
  managed devices (name, OS/version, compliance, management state, owner
  type, primary user, last check-in, serial/UDID/IMEI), filterable and
  CSV-exportable. No remote actions (wipe/retire/sync) in this phase --
  see "Deferred" below.
- **Exchange mailbox basics**: a real Exchange page covering mailbox
  aliases, automatic replies, rule-based mail forwarding (via an inbox
  rule this app manages -- see "Deferred" below for why this isn't native
  forwarding), and a read-only mailbox usage/quota report. External
  forwarding destinations are called out explicitly and require
  confirmation to enable.
- **Impact-preview safety framework**: deleting or disabling a single
  selected user now shows what's cheaply known about them first --
  licenses, group and admin-role memberships, and last sign-in if the
  tenant has Azure AD Premium -- before you confirm. Delete requires
  typing the user's display name to confirm; disable uses a plain
  confirmation, since it's reversible. Bulk (multi-select) actions still
  use a plain named confirmation rather than building one preview per row.

### Fixed
- Every list-fetching call in the app (Users, Groups, Devices, etc.) now
  follows `@odata.nextLink` to retrieve every page of results. Previously
  each call fetched only the first page (up to 999 rows) and silently
  stopped there -- a tenant with more than 999 users or devices was
  missing rows with no indication anything was cut off.

### Changed
- The app now requests `DeviceManagementManagedDevices.Read.All`,
  `Mail.ReadWrite`, and `Reports.Read.All` at sign-in alongside the
  existing core scopes. **Existing installs will need to sign in again**
  (and the tenant's admin-consent grant may need refreshing) to pick these
  up.

### Deferred (and why)
- **Intune remote actions** (wipe/retire/sync/etc.): out of scope for this
  phase by design -- these are higher-consequence than read-only
  inventory and deserve their own confirmation/impact-preview treatment
  rather than being rushed in alongside everything else above.
- **Native Exchange forwarding** (`Set-Mailbox -ForwardingSmtpAddress`):
  Microsoft Graph has no property corresponding to this anywhere in the
  SDK -- it's genuinely EXO-PowerShell-only. Rule-based forwarding (an
  inbox rule) is the closest Graph-native substitute and is labeled as
  such throughout, never called "mailbox forwarding" unqualified.
- **Shared mailbox identification**: there's no reliable Graph signal on
  the `user` resource to tell a shared mailbox apart from a regular one,
  so this app doesn't try to guess.
- **Custom RBAC role definitions** and **PIM-eligible (as opposed to
  active) role assignments**: unchanged limitation from the classic
  directory-roles API this app uses for free-tier compatibility (see
  v0.3.0's Roles fix, below).

## [0.3.0] - 2026-07-06

### Added
- **Devices**: list/search Entra-registered/joined devices (name, OS,
  trust type, compliance, managed status, last sign-in), enable/disable and
  delete with multi-select bulk actions. This is device *identity* data, not
  Intune's device management data (still a separate, unimplemented module).
- **Sign-in logs**: read-only recent sign-in activity, including which
  device (if any) was used, filterable by user. Only requires Azure AD
  Premium P1+ to actually return data, so the page is only shown when tenant
  capability detection finds that licensing -- a tenant without Premium
  never sees it rather than getting an empty or erroring page.

### Fixed
- **Roles (RBAC) always showed "0 role(s)"** on tenants without Azure AD
  Premium. It was built on the newer unified RBAC API
  (`/roleManagement/directory/*`), which is the API PIM eligible-assignment
  scheduling uses -- and it turns out that API requires Premium to return
  *any* data, silently, with no error, even though plain role assignment is
  a free-tier Entra feature. Switched to the classic `/directoryRoles` +
  `/directoryRoleTemplates` API, which works on every tier and uses the same
  add/remove-member pattern already proven out in Groups. The one trade-off:
  this classic API only covers built-in roles, not custom ones -- but
  creating a custom role itself requires Premium, so a free-tier tenant has
  none to miss.

### Changed
- The app now requests `Device.ReadWrite.All` and `AuditLog.Read.All` at
  sign-in alongside the existing core scopes. **Existing installs will need
  to sign in again** (and the tenant's admin-consent grant may need
  refreshing) to pick these up, since a cached token won't have them yet.

### Notes
- Sign-in log filtering matches the start of a user's display name or
  user principal name (Graph's sign-in logs don't support the `$search`
  used elsewhere in the app).

## [0.2.0] - 2026-07-06

First release with real directory administration -- previous releases only
had the app shell and placeholder pages.

### Added
- **Users**: list/search, create, edit profile fields (display name, job
  title, department, office location, mobile phone, usage location), reset
  password, enable/disable and delete with multi-select bulk actions.
- **Groups**: list/search, create (Security or Microsoft 365), delete, and
  manage membership (add/remove by UPN or object ID) via a members panel
  next to the group list.
- **Licensing**: tenant-wide subscribed-SKU consumption table, plus a
  per-user license assignment panel (checklist of SKUs, applies add/remove
  in one call to `assignLicense`). Warns if the user has no usage location
  set, since Graph requires one before a license can be assigned.
- **Roles (RBAC)**: list Entra directory role definitions (built-in and
  custom), view who's assigned to a selected role, and assign/remove a
  user's assignment. Intune and Exchange RBAC remain out of scope (different
  permission models) -- see `docs/DESIGN.md` section 6.
- Plain-language handling of authorization failures: every write action is
  always offered regardless of the signed-in admin's actual role, and a 403
  from Graph now surfaces as "you don't have permission to do this, it
  typically requires role X" instead of a raw exception. This is deliberate
  -- the app doesn't try to predict permissions client-side, since Graph
  itself is the only reliable source of truth for what a given admin can do.

### Notes
- Group membership resolves a typed-in UPN to its object ID automatically;
  role assignment currently supports user principals only (not groups or
  service principals).
- Dynamic membership rules, group-based licensing, and PIM-eligible (as
  opposed to active) role assignments are not yet implemented.

## [0.1.2] - 2026-07-06

### Fixed
- Sign-in crashed silently before ever opening a browser: the "announce this
  status change to screen readers" helper called `QAccessible.QAccessibleEvent`,
  which doesn't exist -- `QAccessibleEvent` is a top-level `QtGui` class, not
  nested under `QAccessible`. The status label was updated to "Signing in to
  ..." right before the crash, so the app looked permanently stuck there with
  no error, no browser, and no indication anything had gone wrong. Automated
  tests never caught this because they run with `QT_QPA_PLATFORM=offscreen`,
  where `QAccessible.isActive()` is always `False`, so the buggy line never
  executed; a new test forces that flag on to exercise the real code path.

## [0.1.1] - 2026-07-06

### Fixed
- The **Tenant > Settings...** menu item was silently moved off the Tenant
  menu on macOS. Qt's default action `MenuRole` scans an action's text for
  words like "settings"/"preferences" and relocates matching actions to the
  macOS application menu (next to the Apple logo); "Settings..." tripped that
  heuristic and ended up there instead of staying in the Tenant menu as
  intended, making it look like the option didn't exist at all. Settings,
  Sign in, and Sign out are now pinned to `MenuRole.NoRole` so they stay in
  the Tenant menu on every platform. ("Exit" is left on the default heuristic
  on purpose -- moving to "Quit GraphicalCloudManager" under the macOS app
  menu is the expected native behavior there.)

## [0.1.0] - 2026-07-06

First release of **Graphical Cloud Manager** — an accessible, cross-platform
desktop app for administering Microsoft Entra, Intune, and Exchange.

### Added
- Architecture and design document (`docs/DESIGN.md`): tech stack rationale
  (PySide6, MSAL delegated auth, Microsoft Graph SDK, optional Exchange Online
  PowerShell bridge), auth model, tenant capability detection, and the
  accessibility implementation strategy.
- Delegated, interactive sign-in via MSAL, with the token cache encrypted at
  rest through the OS credential store (Keychain/Credential Manager/Secret
  Service).
- On-disk config file (Tenant ID, Client ID) editable through an in-app
  **Tenant > Settings...** dialog, so the app isn't tied to a hardcoded app
  registration.
- Tenant capability detection (via `subscribedSkus`): the Intune and Exchange
  sections only appear, and their scopes are only requested, when the signed-in
  tenant is actually licensed for them.
- Main window shell with a keyboard-navigable section list (Users, Groups,
  Licensing, Roles, and conditionally Intune/Exchange) and placeholder pages
  for each; the underlying management features are not yet implemented.
- Automated accessibility audit (`pytest`) that walks every window/dialog and
  fails if a button, field, combo box, or list is missing an accessible name.

### Notes
- This is an early scaffold: Users/Groups/Licensing/Roles/Intune/Exchange do
  not yet perform real directory operations. See `docs/DESIGN.md` section 10
  for the roadmap.
- Binaries are unsigned: macOS Gatekeeper and Windows SmartScreen will warn on
  first launch (right-click → Open on macOS; More info → Run anyway on
  Windows).
- Before signing in, register your own Entra app (public client, redirect URI
  `http://localhost`) and set its Client ID / Tenant ID via **Tenant >
  Settings...** — see the README for step-by-step instructions.

[Unreleased]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/mediaswing/graphical-cloud-manager/releases/tag/v0.1.0

# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

On each tagged release (`vX.Y.Z`), the CI workflow publishes the matching
section below as the GitHub Release notes.

## [Unreleased]

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

[Unreleased]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/mediaswing/graphical-cloud-manager/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/mediaswing/graphical-cloud-manager/releases/tag/v0.1.0

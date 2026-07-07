# Graphical Cloud Manager — Design Document

## 1. Goals

A desktop GUI, cross-platform (Windows/macOS/Linux) application for administering:

- **Microsoft Entra ID** — users, groups, licensing, directory roles (RBAC), always present.
- **Microsoft Intune** — device/app/config management, shown only if the connected tenant has Intune licensing.
- **Exchange Online** — mailbox/mail-flow management, shown only if the connected tenant has Exchange Online licensing.

Non-negotiable constraints:

- Fully operable by keyboard alone (no mouse-only affordances).
- Every interactive control has an accessible name/description a screen reader can announce (NVDA/JAWS/Narrator on Windows, VoiceOver on macOS, Orca on Linux).
- Runs the same way on Windows, macOS, and Linux.

## 2. Tech stack

| Concern | Choice | Why |
|---|---|---|
| GUI toolkit | **PySide6** (Qt for Python, LGPL) | Qt's accessibility framework bridges to native screen readers on all three target OSes. Widgets are native-rendered (not canvas-drawn like Tkinter), so the platform accessibility tree sees real controls. LGPL license is compatible with this project's MIT license without a commercial Qt license (unlike PyQt6's GPL/commercial dual licensing). |
| Auth | **MSAL for Python**, interactive/broker delegated flow | The admin using the tool signs in as themselves; Conditional Access and MFA apply naturally; the app never holds tenant-wide standing privilege. |
| Graph access | **Microsoft Graph SDK for Python** (`msgraph-sdk`, Kiota-generated, async/httpx-based) | Official, typed, handles retries/paging; covers Entra, Intune (`/deviceManagement/*`), and partial Exchange (`/users/{id}/mailboxSettings`, mail-enabled groups). |
| Exchange gaps | Shell out to **Exchange Online PowerShell (EXO V3 module)** via `pwsh`, JSON in/out over a subprocess bridge | Graph's Exchange admin coverage is incomplete (mail flow rules, distribution group management details, litigation hold, retention). EXO V3 supports the same delegated user token via REST-based auth, so no separate credential is needed. This module is optional — if `pwsh` + `ExchangeOnlineManagement` aren't present, Exchange features that need them are disabled with an explanation, not a crash. |
| Async/UI bridge | **qasync** | Runs one asyncio loop inside Qt's event loop so Graph SDK calls stay non-blocking without a manual thread pool. |
| Credential storage | **keyring** (Credential Manager / Keychain / Secret Service) | MSAL's token cache is serialized and encrypted at rest per OS, not written to a plain file. |
| Packaging | **PyInstaller**, wrapped per-OS (Inno Setup on Windows, `create-dmg` + notarization on macOS, AppImage/`.deb` via `fpm` on Linux) | Produces a native-feeling installer per platform from one codebase. |
| Testing | `pytest`, `pytest-qt` for interaction tests; manual screen-reader pass (NVDA, VoiceOver, Orca) as a release gate, not an afterthought | Automated tests catch regressions in logic and focus order; only a real screen reader catches announcement quality. |

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│ UI layer (PySide6)                                       │
│  MainWindow → Sidebar nav (Users, Groups, Licensing,      │
│  Roles, Intune*, Exchange*) → Page widgets                │
│  * shown only if tenant capability detection finds them   │
├─────────────────────────────────────────────────────────┤
│ Service layer (plain Python, no Qt imports)               │
│  UserService, GroupService, LicenseService, RbacService,   │
│  IntuneService, ExchangeService                            │
│  — each wraps Graph calls / PowerShell bridge calls into   │
│    plain dataclasses the UI layer consumes                │
├─────────────────────────────────────────────────────────┤
│ Integration layer                                          │
│  GraphClient (msgraph-sdk, async)                          │
│  ExoBridge (subprocess → pwsh → ExchangeOnlineManagement)  │
│  AuthManager (MSAL interactive + silent token refresh)      │
├─────────────────────────────────────────────────────────┤
│ Platform services                                          │
│  keyring (token cache), qasync (event loop), logging        │
└─────────────────────────────────────────────────────────┘
```

The service layer is UI-framework-agnostic on purpose: it can be unit-tested without Qt, and it's the seam a future CLI or a different frontend could reuse.

## 4. Auth & multi-tenant model

- Eventually, one **multi-tenant Entra app registration** (public client, no secret) ships with the app, with a fixed client ID baked in. Each customer's Global Admin performs a one-time admin-consent grant for the delegated scopes below.
- Until that registration exists (i.e. during development/testing), the client ID and tenant ID are supplied by whoever is running the app via an on-disk config file (see section 4a) rather than hardcoded, so anyone can point a build at their own test app registration and tenant without editing source.
- Sign-in uses MSAL's interactive flow (system browser or embedded webview) with the OS token broker where available, falling back to device-code flow for remote/headless sessions.
- The app supports multiple saved **connection profiles** (one per tenant an MSP-style user manages). Each profile stores only a tenant hint and cache key; the actual refresh token lives in MSAL's encrypted cache via `keyring`.
- Scopes are **not yet requested incrementally** -- there's no per-capability consent wired up, so every scope in `auth_manager.CORE_SCOPES` is requested unconditionally at every sign-in, and a tenant/role that can't use a given scope simply gets a 403 on the calls that need it (surfaced via `graph_errors.friendly_error_message`, never a crash). `CORE_SCOPES` as of this writing:
  - `User.ReadWrite.All`, `Group.ReadWrite.All`, `Organization.Read.All` (tenant/capability detection), `Directory.ReadWrite.All` (group/user license assignment, dynamic membership rules)
  - `RoleManagement.ReadWrite.Directory` (Entra directory roles)
  - `Device.ReadWrite.All` (Entra device identity, not Intune-managed device data)
  - `AuditLog.Read.All` (sign-in logs; a scope can always be requested, it's the *data* that needs Azure AD Premium P1+, so capability detection hides the page rather than gating the scope)
  - `DeviceManagementManagedDevices.Read.All` (Intune device inventory -- **read-only**; there is no corresponding write scope requested, since this phase has no remote-action or write capability at all, see section 6)
  - `Mail.ReadWrite` (rule-based mail forwarding via an inbox `messageRule`, and mailbox settings beyond what any read-only call needs)
  - `Reports.Read.All` (mailbox usage/quota report, a CSV-returning endpoint)
  - Custom RBAC role definitions and PIM-eligible (as opposed to active) role assignments remain unimplemented, so no scope is requested for either.
  - **Existing installs must sign out/in again whenever this list grows** (each release's CHANGELOG entry calls out newly added scopes) since a cached token won't carry scopes it wasn't originally issued with.

## 4a. Config file

`gcm.config` reads/writes a small TOML file (`client_id`, `tenant_id`) from an OS-standard per-user config directory:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/GraphicalCloudManager/config.toml` |
| Windows | `%APPDATA%\GraphicalCloudManager\config.toml` |
| Linux | `$XDG_CONFIG_HOME/GraphicalCloudManager/config.toml` (falls back to `~/.config/...`) |

`GCM_CONFIG_PATH` overrides the path entirely (used by tests to avoid touching a real user's config). The in-app **Tenant > Settings...** dialog (`ui/settings_dialog.py`) edits this file; it never needs to be hand-edited, though it's plain TOML if you want to.

This file holds no secret -- a public client's Application (client) ID and a tenant ID are not credentials -- so it does not need `keyring`-level protection the way cached tokens do.

## 5. Tenant capability detection

On successful sign-in, the app calls `GET /subscribedSkus` and inspects `servicePlans` for Intune (`servicePlanName` containing `INTUNE`), Exchange Online (`EXCHANGE_S_*` / `EXCHANGEONLINE`), and Azure AD Premium (`AAD_PREMIUM`, which also matches P2's `AAD_PREMIUM_P2` as a substring). The sidebar only shows Intune/Exchange/Sign-in logs if the corresponding service plan is present and enabled — a tenant without Intune never sees an Intune tab, and a tenant without at least Premium P1 never sees Sign-in logs (which would otherwise just show a permissions/licensing error).

## 6. Feature modules

| Module | Status | Notes |
|---|---|---|
| Users | Implemented | List/search, create, edit profile fields (incl. `usageLocation`, needed before a license can be assigned), reset password, enable/disable and delete with multi-select bulk actions, CSV export. Delete and Disable on a single selected user show an **impact preview** (licenses, group/admin-role memberships, last sign-in if Premium) before confirming -- see section 6f. Delete requires typing the user's display name to confirm; bulk (multi-select) actions fall back to a plain named confirmation, since building one impact preview per row would scale Graph traffic with selection size |
| Groups | Implemented | Security + Microsoft 365 groups: list/search, create, delete, add/remove members by UPN or object ID, CSV export, dynamic membership rule editing (section 6e) |
| Bulk user import | Implemented | Import users from a CSV file (template: `docs/bulk_import_template.csv`) -- full validation of every row before anything runs (required columns, UPN format, duplicate UPNs within the file, existing-user check), a preview distinguishing blocking errors from non-blocking warnings, then execution with bounded concurrency (`asyncio.Semaphore`) so one row's failure never stops the rest. Every row's outcome (success or failure) is shown in a results table and exportable to CSV -- never silently dropped |
| Licensing | Implemented | Two panels: per-user license assignment (checklist of SKUs, applies add/remove in one call to `assignLicense`, warns if usage location isn't set) and **group-based licensing** (assign/remove a license at the group level via `Group.assignLicense`, showing `licenseProcessingState` with an explicit "Microsoft may take some time to finish applying this" note rather than implying instant effect). The per-user view also distinguishes licenses assigned directly from ones inherited through a group, via `licenseAssignmentStates[].assignedByGroup` |
| RBAC | Entra directory roles only | List built-in role definitions, view who's assigned to a role, assign/remove a user's assignment. Built on the classic `/directoryRoles` + `/directoryRoleTemplates` API rather than the unified RBAC API, which requires Azure AD Premium to return data at all -- see `services/role_service.py`'s module docstring. Custom role definitions and PIM-eligible (as opposed to active) assignments are not implemented. Intune RBAC (scope tags) and Exchange RBAC (management role groups) are explicitly out of scope — different permission models, deferred to a later phase |
| Devices | Implemented | Entra-registered/joined devices: list/search, enable/disable, delete with multi-select bulk actions, CSV export. This is device *identity* data (OS, trust type, compliance flag, last sign-in) via `/devices` -- it is not Intune's device management data (see Intune, below). Right-clicking a row offers **Sync with Intune** (see section 6c) -- shown regardless of tenant capability, so a tenant without Intune gets a clear error rather than a hidden/absent action |
| Sign-in logs | Implemented, Premium-gated | Read-only recent sign-in activity via `/auditLogs/signIns`, including which device (if any) was used, filterable by user, CSV export. Only shown when capability detection finds Azure AD Premium P1 or higher, since the underlying data doesn't exist without it |
| Audit log (local) | Implemented | A local, client-side log of every write action this app performs (actor, timestamp, action, target, success/failure, before/after state where relevant) -- see section 6a. Filterable, searchable, CSV-exportable. This is a convenience log for the person running this app; it is not a replacement for Entra/Intune/Exchange's own server-side audit logs, which remain authoritative and are unaffected by anything in this app |
| Intune | Implemented, mostly read-only | Device inventory (`/deviceManagement/managedDevices`): name, OS/version, compliance state, management state/agent, owner type, primary user, last check-in, serial/UDID/IMEI. Filterable, CSV-exportable. Only visible if capability detection finds Intune; a missing-permission or no-Intune response shows a clear status message rather than a crash or empty table. The one remote action implemented is **Sync**, offered via right-click on the Devices page (not this page) -- see section 6c. **Wipe/retire/restart** remain out of scope, by design |
| Exchange | Implemented, partial | Mailbox aliases (`proxyAddresses`, read/write via existing `User.ReadWrite.All`), automatic replies (`mailboxSettings.automaticRepliesSetting`, read/write), **rule-based mail forwarding** (an inbox `messageRule` this app creates/edits/removes by a recognizable name -- read/write, requires `Mail.ReadWrite`), and a read-only mailbox usage/quota report (requires `Reports.Read.All`, returns raw CSV, may show anonymized identities depending on a tenant admin-center privacy toggle this app doesn't control). See section 6d for what's deliberately not implemented and why. Only visible if capability detection finds Exchange Online |

Every write action can fail with an authorization error if the signed-in admin's actual directory role doesn't permit it — the app doesn't try to predict this client-side (Entra's real permission model is too nuanced to reliably mirror in the UI). Instead, `services/graph_errors.py` turns a Graph `Authorization_RequestDenied` (HTTP 403) response into a plain-language explanation shown in a dialog, rather than a raw exception. This is the deliberate "full administration if permissions allow" behavior: every action is always offered, and Graph itself is the source of truth for whether it's actually allowed.

## 6a. CSV export/import

`services/csv_io.py` provides two plain functions used by every exportable page and by bulk import: `export_rows` (stdlib `csv.writer`, `QUOTE_MINIMAL`, `newline=""`, `utf-8-sig` encoding so Excel opens Unicode content correctly) and `read_rows` (stdlib `csv.DictReader`). Both run off the UI thread via `loop.run_in_executor`, called from `widgets/csv_export_button.py` (a single shared `AccessibleButton`-based widget: native accessible save dialog, then export, then a success/row-count or failure message on the page's existing status label) so exporting a large dataset never freezes the window. No page implements its own CSV logic.

## 6b. Local audit log

`services/audit_log.py` appends one JSON line per write action to `audit.jsonl` in the same per-OS app-data directory `config.py` already uses (`GCM_AUDIT_LOG_PATH` overrides it for tests). JSONL means old entries are never rewritten, and a size cap (last 5,000 entries, trimmed on write) keeps the file bounded. `set_actor(username)` is called once after a successful sign-in; `record(...)` is called explicitly at each write call site inside services -- deliberately not a generic decorator/wrapper, so a new write method can't accidentally have its arguments logged verbatim (e.g. `reset_password` logs that a reset happened and whether the user must change it at next sign-in, **never the new password itself**). `ui/pages/audit_log_page.py` is the viewer: filter by text/result, CSV export, always visible (it's local data, not tenant data, so it isn't capability-gated).

## 6c. Intune (read-only inventory, plus Sync)

`services/intune_device_service.py` has two methods: `list_managed_devices` (read-only) and `sync_device_by_azure_ad_device_id`. Sync is the one remote action implemented so far -- it's the least consequential of Intune's remote actions (no data loss, fully reversible, just asks the device to check in now), so it uses the plain `confirm_destructive` Yes/No prompt rather than the impact-preview framework (section 6f). Wipe, retire, and remote lock remain deferred: they're higher-consequence, need their own confirmation/impact-preview treatment, and weren't rushed in alongside this or the other launch features.

Sync is offered from the **Devices page** (Entra devices), not the Intune page, via right-click -- deliberately, because Devices is shown regardless of tenant capability while the Intune page only exists when capability detection finds Intune. This lets a tenant without Intune get an explicit "Intune not available" message when they try the action, instead of the feature simply not existing anywhere reachable. It also means the action has to bridge two different ID spaces: `DeviceSummary.id` (used throughout the Devices page) is the Entra device's Graph object ID from `/devices`, while Intune's `syncDevice` action needs the *managedDevice* ID from `/deviceManagement/managedDevices` -- a different resource entirely. The two are correlated via Entra's own `deviceId` property (`DeviceSummary.azure_ad_device_id`) matched against `ManagedDevice.azureADDeviceId`, resolved with one extra Graph lookup (`managedDevices?$filter=azureADDeviceId eq '{deviceId}'`) before the sync call. If that lookup finds nothing, the service raises a friendly "this device isn't enrolled in Intune" error -- a distinct, expected outcome from the tenant having no Intune at all, and handled the same way any other write failure is (section 8): shown via `friendly_error_message`, never a raw exception.

## 6d. Exchange: what's implemented vs. deliberately not

Every capability below was checked against the actual installed `msgraph-sdk`, not assumed from general Graph knowledge:

- **Rule-based forwarding vs. native forwarding**: Graph has no property anywhere corresponding to Exchange's classic `Set-Mailbox -ForwardingSmtpAddress` -- it's genuinely unavailable outside EXO PowerShell. The substitute this app uses is a normal inbox rule (`messageRule` with a `forwardTo`/`redirectTo` action), which *is* fully supported via Graph. This is a different mechanism (visible/editable by the mailbox owner in Outlook, not a hidden admin-only attribute) and is labeled "rule-based forwarding" everywhere in the UI, never called "mailbox forwarding" unqualified. When the destination address's domain differs from the tenant's own domain, the UI calls this out explicitly as external forwarding and requires confirmation before enabling it.
- **Shared mailbox identification**: there is no reliable Graph signal on the `user` resource to distinguish a shared mailbox from a regular one. Not implemented -- guessing here would risk exposing/hiding the wrong controls for a given mailbox.
- **Mailbox usage/quota report**: `reports.get_mailbox_usage_detail_with_period(...)` returns raw CSV `bytes`, not JSON, parsed via stdlib `csv.DictReader`. Lowest-priority of the Exchange features; Microsoft may anonymize identities in this report depending on a tenant-wide admin-center privacy toggle this app has no control over, so the UI notes that possibility rather than assuming the data is always attributable.

## 6e. Dynamic group rule editor

`ui/dialogs/dynamic_rule_dialog.py` combines a raw rule-text editor (pre-filled with the group's existing `membershipRule`, never blanked unless the admin actually edits it) with a guided builder for common single-condition rules (attribute/operator/value dropdowns that compose into rule text inserted into the raw editor -- the builder never parses or rewrites existing rule text, only appends new text) and a preview pane. Client-side validation (balanced quotes/parens, non-empty, `user.`/`device.` prefix matching the group's member type) is a syntax sanity check only -- the dialog is explicit that passing local validation is not a guarantee Entra will accept the rule, since only Entra itself fully validates rule semantics. `group_service.set_membership_rule` merges `"DynamicMembership"` into the group's existing `groupTypes` rather than overwriting the array, so turning on a dynamic rule can never silently drop an M365 group's `"Unified"` flag.

## 6f. Impact-preview safety framework

`services/impact_preview.py` + `ui/widgets/impact_preview_dialog.py` centralize a single reusable pattern for confirming destructive/high-impact single-target actions: a small, fixed number of targeted Graph calls (one user GET, one `subscribedSkus` GET, one capped `memberOf` GET with `$top=20`, and -- only if the tenant has Azure AD Premium -- one last-sign-in lookup) build an `ImpactPreview` showing licenses, group and admin-role memberships, and last sign-in. Each sub-fetch is wrapped independently so one failing call degrades to a warning rather than blocking the whole preview, and the dialog always states plainly what it does *not* check (app role assignments, administrative unit scoping, resource-level Azure RBAC) rather than implying completeness. Two confirmation strengths share the same dialog: a plain Yes/No for reversible actions (e.g. disabling a user) and a stronger type-the-display-name-to-confirm gate for irreversible ones (e.g. deleting a user). Currently wired into Users' Delete and Disable actions as the reference implementation; documented here as the pattern any future destructive action (e.g. Intune remote actions, if added later) should reuse rather than rolling its own confirmation.

## 7. Accessibility implementation strategy

Concrete Qt techniques, not just intent:

- **Accessible names on everything**: every `QWidget` subclass used interactively (buttons, table views, combo boxes, checkboxes) gets `setAccessibleName()` and, where the visible label alone is ambiguous, `setAccessibleDescription()`. Icon-only buttons (e.g. a trash-can delete icon) always get an accessible name even though no visible text label exists — audited automatically in CI (see below).
- **Keyboard navigation**: explicit, tested tab order via `setTabOrder`; no keyboard traps (verified in `pytest-qt` by asserting every dialog can be closed via `Esc` and every actionable control is reachable via `Tab`/`Shift+Tab` alone); mnemonics (`&Save`) on all buttons/menu items; `Enter`/`Space` activates the focused control; arrow keys navigate list/table rows using Qt's built-in item-view keyboard handling (not custom-reimplemented, which tends to break screen-reader row announcements).
- **Tables/lists**: `QTableView`/`QTreeView` with a proper `QAbstractItemModel`, not manually-drawn grids — this is what lets Qt's accessibility bridge expose row/column/header semantics to AT-SPI/UIA/NSAccessibility correctly.
- **Focus visibility**: the app stylesheet never removes Qt's focus rectangle; a visible focus indicator is a hard requirement, checked in code review.
- **Status/error announcements**: transient toasts and validation errors fire `QAccessible::updateAccessibility` with an `Alert` event so screen readers announce them proactively, instead of relying on the user to discover a silent visual-only message.
- **No color-only signaling**: compliance/status indicators (e.g. device compliant/non-compliant) always pair an icon + text label with color, never color alone.
- **Automated accessible-name audit**: a `pytest` pass walks the widget tree of every page and fails if any `QAbstractButton`/`QAction`/`QLineEdit` lacks an accessible name — catches regressions before a human ever needs to test with a screen reader.
- **Manual screen-reader pass as a release gate**: NVDA (Windows), VoiceOver (macOS), Orca (Linux) — each core workflow (sign in, create a user, assign a license, assign a role) walked end-to-end with the screen reader as the only feedback channel, before each release.

## 8. Security considerations

- No client secret ships with the app (public client + interactive delegated auth only) — nothing to leak from a distributed binary.
- Token cache encrypted at rest via OS credential store, never written as plaintext JSON.
- Scopes are requested unconditionally at sign-in (see section 4), not yet incrementally per capability -- a compromised/malicious build could attempt anything in `CORE_SCOPES`, but every attempt still runs as the signed-in admin's own delegated identity, subject to their actual Entra role, Conditional Access, and MFA; the app never holds standing tenant-wide privilege of its own.
- Every write operation (license change, role assignment, group membership change, mailbox rule change, bulk import row, etc.) is logged locally via `services/audit_log.py` with actor, timestamp, action, target, success/failure, and before/after state where relevant — this is a client-side convenience log, not a replacement for Entra/Intune/Exchange's own audit logs, which remain authoritative. Call sites are explicit (not a generic argument-logging wrapper) specifically so a write method that happens to take a secret (e.g. `reset_password`'s new password) can log that the action happened without ever logging the secret value itself.
- Destructive/high-impact single-target actions (currently: user delete, user disable) go through the impact-preview safety framework (section 6f) rather than a generic "Are you sure?" — irreversible ones require typing the target's display name to confirm. Bulk (multi-select) actions and other destructive actions elsewhere in the app (group delete, device delete, role-assignment removal) use a plain named confirmation (`confirm_destructive`) that states the specific object(s) affected.
- Untrusted input (bulk import CSV) is fully validated -- required columns, UPN format, duplicate detection, existing-user check -- before any Graph write is attempted, and a row that fails validation is skipped and reported, never silently run with partial/garbage data.

## 9. Project layout

```
src/gcm/
  app.py                    # entry point, builds QApplication + qasync loop
  auth/
    auth_manager.py          # MSAL interactive/silent flow, profile switching, CORE_SCOPES
    token_cache.py           # keyring-backed MSAL SerializableTokenCache
  graph/
    client.py                # GraphClient wrapper over msgraph-sdk
    capabilities.py           # subscribedSkus → Intune/Exchange/Premium presence
    pagination.py             # collect_all(): follows @odata.nextLink via msgraph_core.PageIterator
  services/
    user_service.py
    group_service.py
    license_service.py        # per-user + group-based licensing
    role_service.py            # Entra directory roles only, see section 6
    device_service.py           # Entra device identity, not Intune management data
    sign_in_log_service.py      # Premium-gated, see section 6
    intune_device_service.py     # read-only inventory, see section 6c
    mailbox_service.py            # Exchange basics, see section 6d
    bulk_import_service.py         # CSV user import, see section 6
    audit_log.py                    # local write-action log, see section 6b
    csv_io.py                        # shared export_rows/read_rows, see section 6a
    impact_preview.py                 # see section 6f
    graph_errors.py                    # ODataError -> plain-language message (esp. 403s)
  config.py                # on-disk app config (tenant ID, client ID) -- see section 4a
  models/                  # plain dataclasses shared by services + UI
                            # (user.py, group.py, license.py, role.py, device.py, sign_in.py,
                            #  intune_device.py, mailbox.py, bulk_import.py, audit_entry.py)
  ui/
    main_window.py
    login_dialog.py
    settings_dialog.py       # edits config.py's on-disk config
    pages/
      users_page.py
      groups_page.py
      devices_page.py
      licensing_page.py
      roles_page.py
      sign_in_logs_page.py
      intune_page.py
      exchange_page.py
      bulk_import_page.py
      audit_log_page.py
    dialogs/
      dynamic_rule_dialog.py    # raw editor + guided builder, see section 6e
    widgets/                # shared accessible widgets: accessible_button.py, confirm.py
                            # (confirm_destructive, confirm_irreversible), csv_export_button.py,
                            # impact_preview_dialog.py, live_region.py
  resources/                # icons, .qss stylesheet
tests/
  test_accessibility_audit.py
  test_services/
  test_pages_*.py, test_confirm_widgets.py, test_impact_preview_dialog.py, ...
docs/
  DESIGN.md
  bulk_import_template.csv
pyproject.toml
```

## 10. Roadmap

Delivered so far: auth, capability detection, Users, Groups, Licensing (per-user and group-based), Entra RBAC, Devices (including right-click Sync with Intune), Sign-in logs (Premium-gated), CSV export, local audit log + viewer, bulk user CSV import, dynamic group rule editor, Intune device inventory, Exchange mailbox basics (aliases, automatic replies, rule-based forwarding, usage report), the impact-preview safety framework, accessibility baseline + automated audit test, packaging for all three OSes.

Not yet implemented, with reasons (not just deferred silently):
- **Intune wipe/retire/restart/lock** -- higher-consequence than Sync (which is implemented, section 6c) and need their own confirmation/impact-preview treatment; explicitly out of scope this phase.
- **Native Exchange forwarding** (`ForwardingSmtpAddress`) -- not exposed via Graph at all, EXO-PowerShell-only; see section 6d.
- **Shared mailbox identification** -- no reliable Graph signal to detect it; see section 6d.
- **Custom RBAC role definitions** and **PIM-eligible (as opposed to active) role assignments** -- the classic directory-roles API this app uses for free-tier compatibility doesn't support either; see section 6.
- **Intune RBAC** (scope tags) and **Exchange RBAC** (management role groups) -- different permission models from Entra directory roles, deferred to a dedicated future feature rather than bolted onto the existing Roles page.

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
- Scopes requested (least privilege, incremental consent where Graph supports it):
  - Core: `User.ReadWrite.All`, `Group.ReadWrite.All`, `Organization.Read.All` (tenant/capability detection), `Directory.Read.All`
  - Licensing: `Directory.ReadWrite.All` (group/user license assignment needs directory write)
  - RBAC (v1 = Entra only): `RoleManagement.ReadWrite.Directory`, `RoleEligibilitySchedule.ReadWrite.Directory` (PIM-eligible assignments, where the tenant is licensed for PIM)
  - Intune (only requested when capability detection finds Intune): `DeviceManagementManagedDevices.ReadWrite.All`, `DeviceManagementConfiguration.ReadWrite.All`, `DeviceManagementApps.ReadWrite.All`
  - Exchange (only requested when capability detection finds Exchange Online): Graph `MailboxSettings.ReadWrite`, plus EXO's own `https://outlook.office365.com/.default` for the PowerShell bridge

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

On successful sign-in, the app calls `GET /subscribedSkus` and inspects `servicePlans` for Intune (`servicePlanName` containing `INTUNE`) and Exchange Online (`EXCHANGE_S_*` / `EXCHANGEONLINE`). The sidebar and the incremental-consent prompts for those scopes only appear if the corresponding service plan is present and enabled — a tenant without Intune never sees an Intune tab or gets asked to consent to device-management permissions.

## 6. Feature modules (v1 scope)

| Module | Status in v1 | Notes |
|---|---|---|
| Users | Full | List/search/create/edit/disable/delete, bulk actions via multi-select |
| Groups | Full | Security + M365 groups, membership management, dynamic membership rule editor |
| Licensing | Full | View `subscribedSkus` consumption, assign/remove licenses per user, group-based licensing |
| RBAC | Entra directory roles only | Built-in + custom role assignment, PIM-eligible assignments where licensed. Intune RBAC (scope tags) and Exchange RBAC (management role groups) are explicitly out of scope for v1 — different permission models, deferred to a later phase |
| Intune | Present, basic | Device inventory, compliance state, basic remote actions (retire/wipe/sync). Only visible if capability detection finds Intune |
| Exchange | Present, basic | Mailbox settings via Graph; mail flow rules/litigation hold via the optional PowerShell bridge. Only visible if capability detection finds Exchange Online |

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
- Scopes requested incrementally and only for capabilities the tenant actually has, minimizing what a compromised/malicious build could do even at maximum consent.
- Every write operation (license change, role assignment, device wipe, mailbox change) is logged locally with actor, timestamp, and before/after state for local audit trail — this is a client-side convenience log, not a replacement for Entra/Intune/Exchange's own audit logs, which remain authoritative.
- Destructive actions (device wipe/retire, user delete, role removal from the last Global Admin) require an explicit confirmation step that names the specific object being affected, not a generic "Are you sure?".

## 9. Project layout

```
src/gcm/
  app.py                  # entry point, builds QApplication + qasync loop
  auth/
    auth_manager.py        # MSAL interactive/silent flow, profile switching
    token_cache.py          # keyring-backed MSAL SerializableTokenCache
  graph/
    client.py               # GraphClient wrapper over msgraph-sdk
    capabilities.py          # subscribedSkus → Intune/Exchange presence
  exchange/
    exo_bridge.py            # subprocess → pwsh → ExchangeOnlineManagement, JSON protocol
  services/
    user_service.py
    group_service.py
    license_service.py
    rbac_service.py
    intune_service.py
    exchange_service.py
  config.py                # on-disk app config (tenant ID, client ID) -- see section 4a
  models/                  # plain dataclasses shared by services + UI
  ui/
    main_window.py
    login_dialog.py
    settings_dialog.py       # edits config.py's on-disk config
    pages/
      users_page.py
      groups_page.py
      licensing_page.py
      roles_page.py
      intune_page.py
      exchange_page.py
    widgets/                # shared accessible widgets (accessible_button.py, data_table.py, ...)
  resources/                # icons, .qss stylesheet
tests/
  test_accessibility_audit.py
  test_services/
docs/
  DESIGN.md
pyproject.toml
```

## 10. Roadmap

1. **v1**: Auth, capability detection, Users, Groups, Licensing, Entra RBAC, accessibility baseline + automated audit test, packaging for all three OSes.
2. **v2**: Intune module (device inventory, compliance, basic remote actions).
3. **v3**: Exchange module (Graph-covered settings first, PowerShell-bridge features second).
4. **v4+**: Intune RBAC (scope tags) and Exchange RBAC (management role groups) as their own dedicated features, given they're different permission models from Entra directory roles.

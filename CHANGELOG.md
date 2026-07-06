# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

On each tagged release (`vX.Y.Z`), the CI workflow publishes the matching
section below as the GitHub Release notes.

## [Unreleased]

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

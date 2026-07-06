# Graphical Cloud Manager

This is a fully accessible, graphical, cross-platform tool for managing Microsoft Entra, Intune, and Exchange.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the architecture, tech stack rationale, auth model, and accessibility implementation strategy.

## Status

Sign-in, capability detection, and the main window/navigation shell are in place. Users, Groups, Licensing, and Roles (Entra directory roles) are implemented against Microsoft Graph -- see `docs/DESIGN.md` section 6 for exactly what each covers. Intune and Exchange are still placeholder pages (see `docs/DESIGN.md` section 10 for the roadmap).

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

### Connect it to a tenant

The app needs an Entra app registration to sign in with. To create one for testing:

1. In the [Entra admin center](https://entra.microsoft.com) (or Azure Portal) go to **App registrations > New registration**.
2. Name it anything, choose the multi-tenant or single-tenant option that matches what you want to test, leave the redirect URI blank for now.
3. Under **Authentication > Add a platform**, choose **Mobile and desktop applications** and check the `http://localhost` redirect URI (MSAL's interactive flow needs this).
4. Under **API permissions**, add the delegated Microsoft Graph scopes listed in `docs/DESIGN.md` section 4, then grant admin consent.
5. Copy the **Application (client) ID** from the app registration's overview page, and your **Directory (tenant) ID** if you're testing against one specific tenant rather than "any org."

Then run the app, open **Tenant > Settings...**, and enter those two values — they're saved to a local config file (see `docs/DESIGN.md` section 4a) so you only need to do this once.

Run the app:

```bash
gcm
# or: python -m gcm.app
```

Then use **Tenant > Settings...** to configure, and **Tenant > Sign in...** to authenticate. Signing in opens your system browser for a normal Microsoft interactive sign-in.

Run tests (includes the automated accessibility audit described in `docs/DESIGN.md` section 7):

```bash
pytest
```

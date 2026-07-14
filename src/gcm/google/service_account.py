"""Domain-wide-delegation credentials for Gmail mailbox admin actions.

Directory API operations (Users/Groups/Devices) use interactive per-admin
OAuth (auth/google_auth_manager.py) because the signed-in admin's own
consent is enough to act on the directory. Gmail mailbox settings are
different: each call is scoped to whichever user's mailbox is being
read/written, and Google has no interactive-consent mechanism for "let me
read someone else's mailbox settings" -- the only way to do that is a
service account granted domain-wide delegation in the Workspace Admin
console, which can then impersonate (`with_subject`) any user in the
domain. That's a separate credential set up by the customer's super admin,
independent of whether an admin is currently signed in interactively.
"""

from __future__ import annotations

from google.oauth2 import service_account

# "basic" covers vacation responder / most settings; "sharing" covers
# delegates and forwarding, which Google treats as more sensitive.
GMAIL_MAILBOX_SCOPES = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.settings.sharing",
]


def build_delegated_credentials(service_account_json_path: str, subject_email: str):
    """A fresh delegated credential impersonating `subject_email`. Built new
    for every call rather than cached/shared: `with_subject` returns a new
    Credentials object rather than mutating the original, and each mailbox
    action here can target a different user, so there's no single long-lived
    client to reuse the way build_directory_client's is."""
    base = service_account.Credentials.from_service_account_file(
        service_account_json_path, scopes=GMAIL_MAILBOX_SCOPES
    )
    return base.with_subject(subject_email)

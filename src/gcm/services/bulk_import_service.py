"""Bulk user creation from a CSV file.

Validation is deliberately split in two:
  1. `parse_and_validate_locally` -- structural checks only (required
     columns/fields, formats, in-file duplicate UPNs). No network calls, so
     it can run on a huge file without hitting Graph at all.
  2. `validate_against_tenant` -- the checks that need Graph data (does this
     UPN already exist, do these license SKUs/groups actually exist in this
     tenant). SKUs and groups are each resolved with *one* list call shared
     across every row; only the per-row existing-user check is inherently
     one call per row, run under bounded concurrency so a large file doesn't
     fire dozens of requests at once.

`execute` only processes rows that passed both validation passes, runs them
under the same bounded concurrency, and never lets one row's failure stop
the others (each row's outcome -- including "user created but a follow-up
step failed" -- is always reported, never silently dropped).
"""

from __future__ import annotations

import asyncio

from kiota_abstractions.api_error import APIError
from msgraph import GraphServiceClient

from gcm.models.bulk_import import ImportRow, ImportRowResult
from gcm.services import csv_io
from gcm.services.graph_errors import friendly_error_message
from gcm.services.group_service import GroupService
from gcm.services.license_service import LicenseService
from gcm.services.user_service import UserService

_REQUIRED_COLUMNS = {"display_name", "user_principal_name", "mail_nickname", "password"}
_DEFAULT_CONCURRENCY = 5

TEMPLATE_CSV = (
    "display_name,user_principal_name,mail_nickname,password,account_enabled,"
    "usage_location,license_skus,groups\n"
    "Jane Doe,jane.doe@contoso.com,jane.doe,TemporaryPassw0rd!,true,US,"
    "ENTERPRISEPACK,Sales Team;All Staff\n"
    "John Roe,john.roe@contoso.com,john.roe,TemporaryPassw0rd!,true,GB,,All Staff\n"
)


class BulkImportFileError(Exception):
    """The file itself can't be processed at all (e.g. missing a required
    column) -- distinct from a single row failing validation."""


class BulkImportService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client
        self._user_service = UserService(graph_client)
        self._group_service = GroupService(graph_client)
        self._license_service = LicenseService(graph_client)

    def parse_and_validate_locally(self, path: str) -> list[ImportRow]:
        """Synchronous and network-free -- call via `loop.run_in_executor`
        for a large file so it never blocks the UI thread."""
        raw_rows = csv_io.read_rows(path)
        if raw_rows:
            missing = _REQUIRED_COLUMNS - set(raw_rows[0].keys())
            if missing:
                raise BulkImportFileError(
                    f"CSV is missing required column(s): {', '.join(sorted(missing))}"
                )

        rows: list[ImportRow] = []
        seen_upns: set[str] = set()
        for i, raw in enumerate(raw_rows, start=1):
            row = _parse_row(i, raw)
            if row.user_principal_name and row.user_principal_name.lower() in seen_upns:
                row.errors.append("Duplicate user principal name within this file.")
            if row.user_principal_name:
                seen_upns.add(row.user_principal_name.lower())
            rows.append(row)
        return rows

    async def validate_against_tenant(
        self, rows: list[ImportRow], *, concurrency: int = _DEFAULT_CONCURRENCY
    ) -> None:
        """Mutates `rows` in place, adding errors/warnings."""
        skus = await self._license_service.list_subscribed_skus()
        sku_by_part_number = {s.sku_part_number.upper() for s in skus}
        groups = await self._group_service.list_groups()
        group_by_name = {g.display_name.lower() for g in groups}

        for row in rows:
            for sku_name in row.license_sku_part_numbers:
                if sku_name.upper() not in sku_by_part_number:
                    row.errors.append(f"Unknown license SKU: {sku_name!r}")
            for group_name in row.group_names:
                if group_name.lower() not in group_by_name:
                    row.errors.append(f"Unknown group: {group_name!r}")

        semaphore = asyncio.Semaphore(concurrency)

        async def check_existing(row: ImportRow) -> None:
            if not row.user_principal_name:
                return
            async with semaphore:
                try:
                    await self._user_service.get_user_detail(row.user_principal_name)
                except APIError as exc:
                    if getattr(exc, "response_status_code", None) == 404:
                        return  # confirmed available
                    row.warnings.append(
                        f"Couldn't verify whether this user already exists: "
                        f"{friendly_error_message(exc)}"
                    )
                    return
                except Exception as exc:
                    row.warnings.append(
                        f"Couldn't verify whether this user already exists: "
                        f"{friendly_error_message(exc)}"
                    )
                    return
                row.errors.append("A user with this user principal name already exists.")

        await asyncio.gather(*(check_existing(row) for row in rows if row.is_valid))

    async def execute(
        self, rows: list[ImportRow], *, concurrency: int = _DEFAULT_CONCURRENCY
    ) -> list[ImportRowResult]:
        skus = await self._license_service.list_subscribed_skus()
        sku_id_by_part_number = {s.sku_part_number.upper(): s.sku_id for s in skus}
        groups = await self._group_service.list_groups()
        group_id_by_name = {g.display_name.lower(): g.id for g in groups}

        semaphore = asyncio.Semaphore(concurrency)
        results: list[ImportRowResult | None] = [None] * len(rows)

        async def process(index: int, row: ImportRow) -> None:
            if not row.is_valid:
                results[index] = ImportRowResult(
                    row.row_number,
                    row.display_name,
                    row.user_principal_name,
                    success=False,
                    message="Skipped: " + "; ".join(row.errors),
                )
                return
            async with semaphore:
                created_user_id: str | None = None
                try:
                    summary = await self._user_service.create_user(
                        display_name=row.display_name,
                        user_principal_name=row.user_principal_name,
                        mail_nickname=row.mail_nickname,
                        password=row.password,
                        account_enabled=row.account_enabled,
                    )
                    created_user_id = summary.id
                    if row.usage_location:
                        await self._user_service.update_user(
                            summary.id, usage_location=row.usage_location
                        )
                    if row.license_sku_part_numbers:
                        add_ids = [
                            str(sku_id_by_part_number[name.upper()])
                            for name in row.license_sku_part_numbers
                        ]
                        await self._license_service.set_user_licenses(
                            summary.id,
                            add_sku_ids=add_ids,
                            remove_sku_ids=[],
                            display_name=row.display_name,
                        )
                    for group_name in row.group_names:
                        await self._group_service.add_member(
                            group_id_by_name[group_name.lower()],
                            summary.id,
                            group_display_name=group_name,
                        )
                except Exception as exc:
                    message = friendly_error_message(exc)
                    if created_user_id:
                        message = f"User created, but a follow-up step failed: {message}"
                    results[index] = ImportRowResult(
                        row.row_number,
                        row.display_name,
                        row.user_principal_name,
                        success=False,
                        message=message,
                    )
                    return
            results[index] = ImportRowResult(
                row.row_number,
                row.display_name,
                row.user_principal_name,
                success=True,
                message="Created successfully.",
            )

        await asyncio.gather(*(process(i, row) for i, row in enumerate(rows)))
        return results


def _parse_row(row_number: int, raw: dict[str, str]) -> ImportRow:
    errors: list[str] = []
    warnings: list[str] = []

    display_name = raw.get("display_name", "").strip()
    upn = raw.get("user_principal_name", "").strip()
    mail_nickname = raw.get("mail_nickname", "").strip()
    password = raw.get("password", "")

    if not display_name:
        errors.append("Display name is required.")
    if not upn:
        errors.append("User principal name is required.")
    elif "@" not in upn:
        errors.append("User principal name must look like an email address (user@domain).")
    if not mail_nickname:
        errors.append("Mail nickname is required.")
    if not password:
        errors.append("Password is required.")
    elif len(password) < 8:
        warnings.append(
            "Password is shorter than 8 characters and may be rejected by Entra's password policy."
        )

    account_enabled_raw = raw.get("account_enabled", "true").strip().lower()
    if account_enabled_raw in ("", "true", "1", "yes"):
        account_enabled = True
    elif account_enabled_raw in ("false", "0", "no"):
        account_enabled = False
    else:
        errors.append(f"account_enabled must be true/false, got {account_enabled_raw!r}.")
        account_enabled = True

    usage_location = raw.get("usage_location", "").strip().upper() or None
    if usage_location and len(usage_location) != 2:
        errors.append("usage_location must be a two-letter country code (e.g. US, GB).")

    license_skus = [s.strip() for s in raw.get("license_skus", "").split(";") if s.strip()]
    groups = [s.strip() for s in raw.get("groups", "").split(";") if s.strip()]

    return ImportRow(
        row_number=row_number,
        display_name=display_name,
        user_principal_name=upn,
        mail_nickname=mail_nickname,
        password=password,
        account_enabled=account_enabled,
        usage_location=usage_location,
        license_sku_part_numbers=license_skus,
        group_names=groups,
        errors=errors,
        warnings=warnings,
    )

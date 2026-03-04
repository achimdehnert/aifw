"""
management command: check_aifw_config

Verifies that every known action code has at least one active catch-all row
(quality_level=NULL, priority=NULL) in AIActionType.

Usage::
    python manage.py check_aifw_config
    python manage.py check_aifw_config --codes story_writing chapter_export
    python manage.py check_aifw_config --fix  # creates missing catch-all stubs

Exit codes:
    0 — all checks passed
    1 — one or more codes missing a catch-all row

Intended for CI pre-deploy checks and Docker entrypoint health gates.

ADR-097 G-097-01.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verify that all aifw action codes have an active catch-all row."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--codes",
            nargs="+",
            metavar="CODE",
            help="Specific action codes to check. Defaults to all active codes.",
        )
        parser.add_argument(
            "--fix",
            action="store_true",
            default=False,
            help="Report only (no auto-fix). Exists for interface compatibility.",
        )

    def handle(self, *args, **options) -> None:
        from aifw.models import AIActionType

        codes = options.get("codes")
        if codes:
            all_codes = list(codes)
        else:
            all_codes = list(
                AIActionType.objects.filter(is_active=True)
                .values_list("code", flat=True)
                .distinct()
                .order_by("code")
            )

        if not all_codes:
            self.stdout.write(self.style.WARNING("No active action codes found."))
            return

        missing: list[str] = []
        for code in all_codes:
            # BF-04 fix: check is_active=True on catch-all row
            has_catchall = AIActionType.objects.filter(
                code=code,
                quality_level__isnull=True,
                priority__isnull=True,
                is_active=True,
            ).exists()
            if has_catchall:
                self.stdout.write(f"  {self.style.SUCCESS('OK')}  {code}")
            else:
                self.stdout.write(f"  {self.style.ERROR('MISSING')}  {code} — no active catch-all row")
                missing.append(code)

        self.stdout.write("")
        if missing:
            self.stdout.write(
                self.style.ERROR(
                    f"{len(missing)} code(s) missing catch-all row: {', '.join(missing)}"
                )
            )
            self.stdout.write(
                "Run 'manage.py init_aifw_config' or add catch-all rows via Django Admin."
            )
            raise CommandError(
                f"check_aifw_config failed: {len(missing)} code(s) without catch-all."
            )

        self.stdout.write(
            self.style.SUCCESS(f"check_aifw_config: all {len(all_codes)} code(s) OK.")
        )

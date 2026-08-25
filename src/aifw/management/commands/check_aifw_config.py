"""
management command: check_aifw_config

Verifies that every known action code has at least one active catch-all row
(quality_level=NULL, priority=NULL) in AIActionType.

With ``--liveness`` it additionally asks every provider whether the models this
registry points at are still served. That second question is the one that went
unasked until 2026-08-25, when the seeded **global default**
``groq/llama-3.3-70b-versatile`` turned out to be retired upstream — with every
catch-all row present and green.

Usage::
    python manage.py check_aifw_config
    python manage.py check_aifw_config --codes story_writing chapter_export
    python manage.py check_aifw_config --liveness   # also ask each provider
    python manage.py check_aifw_config --fix  # creates missing catch-all stubs

Exit codes:
    0 — all checks passed
    1 — one or more codes missing a catch-all row, or a model is retired
        upstream / a configured API key is rejected

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
        parser.add_argument(
            "--liveness",
            action="store_true",
            default=False,
            help="Additionally ask each provider whether its registered models still exist.",
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
                self.stdout.write(
                    f"  {self.style.ERROR('MISSING')}  {code} — no active catch-all row"
                )
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

        if options.get("liveness"):
            self._liveness()

    # ── liveness ────────────────────────────────────────────────────────────

    def _liveness(self) -> None:
        """Ask every provider whether the models we route to still exist."""
        from aifw.liveness import DEFECTS, LIVE, NO_KEY, katalog_fuer, pruefe_modell
        from aifw.models import LLMModel

        modelle = list(
            LLMModel.objects.filter(is_active=True, provider__is_active=True)
            .select_related("provider")
            .order_by("provider__name", "name")
        )
        if not modelle:
            self.stdout.write(self.style.WARNING("No active models — nothing to check."))
            return

        self.stdout.write("")
        self.stdout.write("Model liveness (asking each provider):")

        kataloge: dict[int, object] = {}
        defekte: list[str] = []
        luecken: list[str] = []
        for modell in modelle:
            provider = modell.provider
            if provider.pk not in kataloge:
                kataloge[provider.pk] = katalog_fuer(provider)
            status, detail = pruefe_modell(modell, kataloge[provider.pk])
            pin = f"{provider.name}/{modell.name}"
            if status == LIVE:
                self.stdout.write(f"  {self.style.SUCCESS('LIVE')}  {pin}")
            elif status in DEFECTS:
                self.stdout.write(f"  {self.style.ERROR(status.upper())}  {pin} — {detail}")
                defekte.append(f"{pin} ({status})")
            else:
                # NO_KEY / UNREACHABLE: a coverage gap, not a defect. A checker that
                # goes red because an installation does not use Mistral gets ignored,
                # and then it checks nothing at all.
                marke = "SKIP" if status == NO_KEY else "UNREACHABLE"
                self.stdout.write(f"  {self.style.WARNING(marke)}  {pin} — {detail}")
                luecken.append(pin)

        self.stdout.write("")
        if luecken:
            self.stdout.write(
                self.style.WARNING(f"{len(luecken)} model(s) not checkable: {', '.join(luecken)}")
            )
        if defekte:
            raise CommandError("check_aifw_config --liveness failed: " + ", ".join(defekte))
        bestaetigt = len(modelle) - len(luecken)
        self.stdout.write(self.style.SUCCESS(f"liveness: {bestaetigt} model(s) confirmed served."))

"""
Management Command: promote_feedback

Überführt korrigierte NL2SQLFeedback-Einträge in NL2SQLExample (Few-Shot-Pool).
Nur Einträge mit corrected_sql und promoted=False werden übernommen.

Usage:
    python manage.py promote_feedback
    python manage.py promote_feedback --source odoo_mfg
    python manage.py promote_feedback --min-age-hours 1
    python manage.py promote_feedback --dry-run
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Promoted korrigierte NL2SQLFeedback-Einträge zu NL2SQLExample"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            default="",
            help="SchemaSource-Code filtern (leer = alle Sources)",
        )
        parser.add_argument(
            "--min-age-hours",
            type=int,
            default=1,
            dest="min_age_hours",
            help="Mindest-Alter in Stunden vor Promotion (Standard: 1)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Nur anzeigen, nicht schreiben",
        )

    def handle(self, *args, **options) -> None:
        from aifw.nl2sql.models import NL2SQLExample, NL2SQLFeedback

        source_code = options["source"]
        min_age = timezone.now() - timedelta(hours=options["min_age_hours"])
        dry_run = options["dry_run"]

        qs = NL2SQLFeedback.objects.filter(
            promoted=False,
            corrected_sql__gt="",
            created_at__lte=min_age,
        ).select_related("source")

        if source_code:
            qs = qs.filter(source__code=source_code)

        if not qs.exists():
            self.stdout.write("Keine promotionsfähigen Feedback-Einträge gefunden.")
            return

        promoted_count = 0
        skipped_count = 0

        for fb in qs:
            exists = NL2SQLExample.objects.filter(
                source=fb.source,
                question=fb.question,
            ).exists()

            if exists:
                self.stdout.write(
                    self.style.WARNING(f"  SKIP (Duplicate): {fb.question[:60]}")
                )
                if not dry_run:
                    fb.promoted = True
                    fb.save(update_fields=["promoted"])
                skipped_count += 1
                continue

            self.stdout.write(
                f"  ✓ [{fb.source.code}] [{fb.error_type}] {fb.question[:60]}"
            )

            if not dry_run:
                NL2SQLExample.objects.create(
                    source=fb.source,
                    question=fb.question,
                    sql=fb.corrected_sql,
                    domain="",
                    difficulty=2,
                    is_active=True,
                    promoted_from=fb,
                )
                fb.promoted = True
                fb.save(update_fields=["promoted"])

            promoted_count += 1

        mode = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{mode}Promote abgeschlossen: "
                f"{promoted_count} promoted, {skipped_count} übersprungen"
            )
        )

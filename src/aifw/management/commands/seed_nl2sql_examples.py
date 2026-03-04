"""
Management Command: seed_nl2sql_examples

Befüllt NL2SQLExample mit verifizierten Q→SQL-Paaren für Few-Shot-Prompting.
Idempotent — bestehende Einträge werden nicht überschrieben.

Usage:
    python manage.py seed_nl2sql_examples
    python manage.py seed_nl2sql_examples --source odoo_mfg
    python manage.py seed_nl2sql_examples --clear
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

EXAMPLES = {
    "odoo_mfg": [
        # ── Maschinen ────────────────────────────────────────────────────
        {
            "question": "Welche Maschinen sind gerade in Störung?",
            "sql": (
                "SELECT\n"
                "  name        AS \"Maschine\",\n"
                "  code        AS \"Code\",\n"
                "  hall        AS \"Halle\",\n"
                "  state       AS \"Status\"\n"
                "FROM casting_machine\n"
                "WHERE state = 'breakdown' AND active = true\n"
                "ORDER BY name"
            ),
            "domain": "machines",
            "difficulty": 1,
        },
        {
            "question": "Wie viele Maschinen sind in welchem Status?",
            "sql": (
                "SELECT\n"
                "  state       AS \"Status\",\n"
                "  COUNT(*)    AS \"Anzahl Maschinen\"\n"
                "FROM casting_machine\n"
                "WHERE active = true\n"
                "GROUP BY state\n"
                "ORDER BY \"Anzahl Maschinen\" DESC"
            ),
            "domain": "machines",
            "difficulty": 1,
        },
        {
            "question": "Top 5 Maschinen nach aktiven Aufträgen",
            "sql": (
                "SELECT\n"
                "  cm.name                         AS \"Maschine\",\n"
                "  COUNT(DISTINCT col.order_id)    AS \"Aktive Aufträge\"\n"
                "FROM casting_order_line col\n"
                "JOIN casting_machine cm ON cm.id = col.machine_id\n"
                "JOIN casting_order co ON co.id = col.order_id\n"
                "WHERE co.state IN ('confirmed', 'in_production')\n"
                "  AND cm.active = true\n"
                "GROUP BY cm.name\n"
                "ORDER BY \"Aktive Aufträge\" DESC\n"
                "LIMIT 5"
            ),
            "domain": "machines",
            "difficulty": 3,
        },
        {
            "question": "Welche Maschine hat die meiste Wartung?",
            "sql": (
                "SELECT\n"
                "  cm.name     AS \"Maschine\",\n"
                "  cm.state    AS \"Status\",\n"
                "  COUNT(*)    AS \"Wartungsvorgänge\"\n"
                "FROM casting_order_line col\n"
                "JOIN casting_machine cm ON cm.id = col.machine_id\n"
                "WHERE cm.state = 'maintenance'\n"
                "GROUP BY cm.name, cm.state\n"
                "ORDER BY \"Wartungsvorgänge\" DESC\n"
                "LIMIT 1"
            ),
            "domain": "machines",
            "difficulty": 2,
        },
        # ── Gießaufträge ─────────────────────────────────────────────────
        {
            "question": "Wie viele Aufträge gibt es je Status?",
            "sql": (
                "SELECT\n"
                "  state       AS \"Status\",\n"
                "  COUNT(*)    AS \"Anzahl Aufträge\"\n"
                "FROM casting_order\n"
                "GROUP BY state\n"
                "ORDER BY \"Anzahl Aufträge\" DESC"
            ),
            "domain": "casting",
            "difficulty": 1,
        },
        {
            "question": "Welche Aufträge sind aktuell in Produktion?",
            "sql": (
                "SELECT\n"
                "  name                AS \"Auftrag\",\n"
                "  state               AS \"Status\",\n"
                "  date_planned        AS \"Geplant bis\",\n"
                "  total_pieces        AS \"Stückzahl\",\n"
                "  total_scrap_pct     AS \"Ausschuss %\"\n"
                "FROM casting_order\n"
                "WHERE state = 'in_production'\n"
                "ORDER BY date_planned\n"
                "LIMIT 50"
            ),
            "domain": "casting",
            "difficulty": 1,
        },
        {
            "question": "Zeige Aufträge mit Ausschuss über 5%",
            "sql": (
                "SELECT\n"
                "  name                AS \"Auftrag\",\n"
                "  state               AS \"Status\",\n"
                "  total_scrap_pct     AS \"Ausschuss %\",\n"
                "  total_pieces        AS \"Stückzahl\",\n"
                "  date_planned        AS \"Geplant bis\"\n"
                "FROM casting_order\n"
                "WHERE total_scrap_pct > 5\n"
                "ORDER BY total_scrap_pct DESC\n"
                "LIMIT 50"
            ),
            "domain": "casting",
            "difficulty": 1,
        },
        {
            "question": "Welche Aufträge sind diese Woche fällig?",
            "sql": (
                "SELECT\n"
                "  name                AS \"Auftrag\",\n"
                "  state               AS \"Status\",\n"
                "  date_planned        AS \"Fällig am\",\n"
                "  total_pieces        AS \"Stückzahl\"\n"
                "FROM casting_order\n"
                "WHERE date_planned >= date_trunc('week', CURRENT_DATE)\n"
                "  AND date_planned < date_trunc('week', CURRENT_DATE) + INTERVAL '7 days'\n"
                "  AND state NOT IN ('done', 'cancelled')\n"
                "ORDER BY date_planned"
            ),
            "domain": "casting",
            "difficulty": 2,
        },
        # ── Qualität ─────────────────────────────────────────────────────
        {
            "question": "Was ist die QS-Bestehensrate?",
            "sql": (
                "SELECT\n"
                "  COUNT(*) FILTER (WHERE result = 'pass')  AS \"Bestanden\",\n"
                "  COUNT(*) FILTER (WHERE result = 'fail')  AS \"Nicht bestanden\",\n"
                "  COUNT(*)                                  AS \"Gesamt\",\n"
                "  ROUND(\n"
                "    100.0 * COUNT(*) FILTER (WHERE result = 'pass')\n"
                "    / NULLIF(COUNT(*), 0), 1\n"
                "  )                                         AS \"Bestehensrate %\"\n"
                "FROM casting_quality_check"
            ),
            "domain": "casting",
            "difficulty": 2,
        },
        # ── SCM ──────────────────────────────────────────────────────────
        {
            "question": "Welche Einkaufsbestellungen sind überfällig?",
            "sql": (
                "SELECT\n"
                "  name            AS \"Bestellung\",\n"
                "  state           AS \"Status\",\n"
                "  date_expected   AS \"Erwartet am\",\n"
                "  total_amount    AS \"Betrag EUR\"\n"
                "FROM scm_purchase_order\n"
                "WHERE date_expected < CURRENT_DATE\n"
                "  AND state NOT IN ('received', 'cancelled', 'done')\n"
                "ORDER BY date_expected\n"
                "LIMIT 50"
            ),
            "domain": "scm",
            "difficulty": 1,
        },
        {
            "question": "Wie viele SCM-Aufträge laufen aktuell?",
            "sql": (
                "SELECT\n"
                "  state       AS \"Status\",\n"
                "  COUNT(*)    AS \"Anzahl Aufträge\"\n"
                "FROM scm_production_order\n"
                "GROUP BY state\n"
                "ORDER BY \"Anzahl Aufträge\" DESC"
            ),
            "domain": "scm",
            "difficulty": 1,
        },
    ],
}


class Command(BaseCommand):
    help = "Seed NL2SQLExample mit verifizierten Q→SQL-Paaren für Few-Shot-Prompting"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            default="odoo_mfg",
            help="SchemaSource-Code (Standard: odoo_mfg)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Bestehende Beispiele für diese Source löschen (nicht promoted)",
        )

    def handle(self, *args, **options) -> None:
        from aifw.nl2sql.models import NL2SQLExample, SchemaSource

        source_code = options["source"]
        source = SchemaSource.objects.filter(code=source_code, is_active=True).first()
        if not source:
            self.stderr.write(
                self.style.ERROR(
                    f"SchemaSource '{source_code}' nicht gefunden. "
                    "Bitte 'python manage.py init_odoo_schema' ausführen."
                )
            )
            return

        if options["clear"]:
            deleted, _ = NL2SQLExample.objects.filter(
                source=source, promoted_from__isnull=True
            ).delete()
            self.stdout.write(f"Gelöscht: {deleted} manuelle Beispiele")

        examples = EXAMPLES.get(source_code, [])
        if not examples:
            self.stderr.write(self.style.WARNING(f"Keine Beispiele für '{source_code}' definiert"))
            return

        created_count = 0
        skipped_count = 0

        for ex in examples:
            exists = NL2SQLExample.objects.filter(
                source=source, question=ex["question"]
            ).exists()
            if exists:
                skipped_count += 1
                continue

            NL2SQLExample.objects.create(
                source=source,
                question=ex["question"],
                sql=ex["sql"],
                domain=ex.get("domain", ""),
                difficulty=ex.get("difficulty", 1),
                is_active=True,
            )
            created_count += 1
            self.stdout.write(f"  ✓ [{ex.get('domain','')}] {ex['question'][:60]}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSeed abgeschlossen: {created_count} erstellt, {skipped_count} übersprungen\n"
                f"Source: {source_code} | Gesamt aktiv: "
                f"{NL2SQLExample.objects.filter(source=source, is_active=True).count()}"
            )
        )

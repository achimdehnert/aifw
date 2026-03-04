"""
Management Command: validate_schema

Prüft ob jede im Schema-XML referenzierte Tabelle und Spalte
wirklich in der Ziel-DB existiert. Verhindert Schema-Drift nach Migrationen.

Exit-Code 1 bei Fehlern — geeignet für CI/CD-Integration.

Usage:
    python manage.py validate_schema
    python manage.py validate_schema --source odoo_mfg
    python manage.py validate_schema --fix-hints
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from django.core.management.base import BaseCommand


def _get_db_columns(db_alias: str, table_name: str) -> set[str]:
    from django.db import connections
    conn = connections[db_alias]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND table_schema = 'public'",
            [table_name],
        )
        return {row[0] for row in cur.fetchall()}


def _get_db_tables(db_alias: str) -> set[str]:
    from django.db import connections
    conn = connections[db_alias]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        return {row[0] for row in cur.fetchall()}


class Command(BaseCommand):
    help = "Validiert Schema-XML gegen tatsächliche DB-Struktur"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            default="",
            help="SchemaSource-Code filtern (leer = alle aktiven Sources)",
        )

    def handle(self, *args, **options) -> None:
        from aifw.nl2sql.models import SchemaSource

        source_code = options["source"]
        qs = SchemaSource.objects.filter(is_active=True)
        if source_code:
            qs = qs.filter(code=source_code)

        if not qs.exists():
            self.stderr.write(self.style.WARNING("Keine aktiven SchemaSource-Einträge gefunden."))
            return

        total_errors = 0
        total_warnings = 0

        for source in qs:
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"Source: {source.code} (DB: {source.db_alias})")
            self.stdout.write("="*60)

            errors = []
            warnings = []

            try:
                db_tables = _get_db_tables(source.db_alias)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  DB-Verbindung fehlgeschlagen: {e}"))
                total_errors += 1
                continue

            if not source.schema_xml.strip():
                warnings.append("Schema-XML ist leer")
                total_warnings += len(warnings)
                self.stdout.write(self.style.WARNING(f"  WARN: {warnings[0]}"))
                continue

            try:
                root = ET.fromstring(source.schema_xml)
            except ET.ParseError as e:
                errors.append(f"Schema-XML ist kein gültiges XML: {e}")
                total_errors += len(errors)
                self.stderr.write(self.style.ERROR(f"  ERROR: {errors[0]}"))
                continue

            for table_el in root.findall("table"):
                table_name = table_el.get("name", "")
                if not table_name:
                    warnings.append("table-Element ohne name-Attribut gefunden")
                    continue

                if table_name not in db_tables:
                    errors.append(f"Tabelle '{table_name}' existiert NICHT in DB")
                    self.stdout.write(self.style.ERROR(f"  ✗ Tabelle '{table_name}' — nicht in DB"))
                    continue

                db_cols = _get_db_columns(source.db_alias, table_name)
                self.stdout.write(f"  ✓ Tabelle '{table_name}' ({len(db_cols)} Spalten in DB)")

                for col_el in table_el.findall("column"):
                    col_name = col_el.get("name", "")
                    if not col_name:
                        continue
                    if col_name not in db_cols:
                        errors.append(
                            f"Spalte '{table_name}.{col_name}' existiert NICHT in DB"
                        )
                        self.stdout.write(
                            self.style.ERROR(f"    ✗ Spalte '{col_name}' — nicht in DB")
                        )
                    else:
                        self.stdout.write(f"    ✓ {col_name}")

            if not errors and not warnings:
                self.stdout.write(self.style.SUCCESS(f"  → Schema vollständig valide"))
            else:
                for w in warnings:
                    self.stdout.write(self.style.WARNING(f"  WARN: {w}"))
                for e in errors:
                    self.stderr.write(self.style.ERROR(f"  ERROR: {e}"))

            total_errors += len(errors)
            total_warnings += len(warnings)

        self.stdout.write(f"\n{'='*60}")
        if total_errors == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Validierung abgeschlossen: 0 Fehler, {total_warnings} Warnungen"
                )
            )
        else:
            self.stderr.write(
                self.style.ERROR(
                    f"Validierung FEHLGESCHLAGEN: {total_errors} Fehler, {total_warnings} Warnungen"
                )
            )
            raise SystemExit(1)

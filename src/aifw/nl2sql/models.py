"""
aifw.nl2sql.models — SchemaSource Django model.

SchemaSource defines a named DB target + XML schema for NL2SQL generation.
Each source maps to a Django DATABASES alias and contains the schema XML
that is injected into the LLM prompt.
"""
from __future__ import annotations

from django.db import models


class SchemaSource(models.Model):
    """Named schema definition for NL2SQL queries.

    Each instance maps a logical name (code) to:
    - a Django DB alias (db_alias)
    - an XML schema describing tables/columns for the LLM prompt
    - access control (blocked_tables, table_prefix)
    - execution limits (max_rows, timeout_seconds)
    """

    code = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Code",
        help_text="Eindeutiger Identifier, z.B. 'scm_manufacturing'.",
    )
    name = models.CharField(max_length=200, verbose_name="Name")
    db_alias = models.CharField(
        max_length=100,
        default="default",
        verbose_name="DB Alias",
        help_text="Django DATABASES-Alias. 'default' für Haupt-DB.",
    )
    schema_xml = models.TextField(
        blank=True,
        verbose_name="Schema XML",
        help_text=(
            "Schema-Metadaten als XML. Beschreibt Tabellen, Spalten, "
            "Beziehungen und Few-Shot-Beispiele für den LLM-Prompt."
        ),
    )
    table_prefix = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Tabellen-Prefix",
        help_text=(
            "Erlaubter Tabellen-Prefix (z.B. 'scm_'). "
            "Leer = alle Tabellen erlaubt."
        ),
    )
    blocked_tables = models.TextField(
        blank=True,
        default="",
        verbose_name="Geblockte Tabellen",
        help_text=(
            "Kommaseparierte Tabellennamen die nie abgefragt werden dürfen. "
            "Intern werden auth_user, auth_token, django_session etc. immer ergänzt."
        ),
    )
    max_rows = models.IntegerField(
        default=500,
        verbose_name="Max Zeilen",
        help_text="Maximale Ergebniszeilen.",
    )
    timeout_seconds = models.IntegerField(
        default=30,
        verbose_name="Timeout (s)",
        help_text="Query-Timeout in Sekunden.",
    )
    allow_explain = models.BooleanField(
        default=False,
        verbose_name="EXPLAIN erlauben",
        help_text="EXPLAIN ANALYZE für Debug-Zwecke erlauben.",
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    class Meta:
        app_label = "aifw"
        db_table = "aifw_nl2sql_schema_sources"
        verbose_name = "NL2SQL Schema Source"
        verbose_name_plural = "NL2SQL Schema Sources"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} ({self.db_alias})"

    def get_blocked_tables_set(self) -> set[str]:
        """Return set of blocked table names (always includes security-sensitive tables)."""
        always_blocked = {
            "auth_user", "auth_token", "django_session",
            "authtoken_token", "oauth2_provider_accesstoken",
            "res_users_keys",
        }
        custom = {
            t.strip().lower()
            for t in self.blocked_tables.split(",")
            if t.strip()
        }
        return always_blocked | custom

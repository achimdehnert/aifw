"""
aifw.nl2sql.models — SchemaSource, NL2SQLExample, NL2SQLFeedback.

SchemaSource:    Named DB target + XML schema for NL2SQL generation.
NL2SQLExample:   Verified Q→SQL pairs injected as few-shot into LLM prompt.
NL2SQLFeedback:  Auto-captured SQL errors + manual corrections pipeline.
"""
from __future__ import annotations

from django.db import models


class SchemaSource(models.Model):
    """Named schema definition for NL2SQL queries."""

    code = models.CharField(max_length=100, unique=True, verbose_name="Code")
    name = models.CharField(max_length=200, verbose_name="Name")
    db_alias = models.CharField(max_length=100, default="default")
    schema_xml = models.TextField(blank=True, verbose_name="Schema XML")
    table_prefix = models.CharField(max_length=50, blank=True)
    blocked_tables = models.TextField(blank=True, default="")
    max_rows = models.IntegerField(default=500)
    timeout_seconds = models.IntegerField(default=30)
    allow_explain = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "aifw"
        db_table = "aifw_nl2sql_schema_sources"
        verbose_name = "NL2SQL Schema Source"
        verbose_name_plural = "NL2SQL Schema Sources"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} ({self.db_alias})"

    def get_blocked_tables_set(self) -> set[str]:
        always_blocked = {
            "auth_user", "auth_token", "django_session",
            "authtoken_token", "oauth2_provider_accesstoken",
            "res_users_keys",
        }
        custom = {t.strip().lower() for t in self.blocked_tables.split(",") if t.strip()}
        return always_blocked | custom


class NL2SQLExample(models.Model):
    """Verified Q→SQL pairs for few-shot prompting.

    Injected into the LLM system prompt to prevent hallucination
    and teach correct join patterns.

    Lifecycle:
        1. Created manually via seed_nl2sql_examples command or
           promoted automatically from NL2SQLFeedback.corrected_sql.
        2. is_active=True → included in every LLM prompt for this source.
        3. difficulty controls prompt ordering (easy first, hard later).
    """

    source = models.ForeignKey(
        SchemaSource,
        on_delete=models.CASCADE,
        related_name="examples",
        verbose_name="Schema Source",
    )
    question = models.TextField(
        verbose_name="Frage",
        help_text="Natürlichsprachliche Frage exakt wie der User sie stellen würde.",
    )
    sql = models.TextField(
        verbose_name="Verifiziertes SQL",
        help_text="Korrekt und gegen echte DB getestet.",
    )
    domain = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Domäne",
        help_text="z.B. casting, scm, machines — für Filterung.",
    )
    difficulty = models.IntegerField(
        default=1,
        verbose_name="Schwierigkeitsgrad",
        help_text="1=einfach, 2=mittel, 3=komplex. Sortiert Prompt-Reihenfolge.",
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    promoted_from = models.ForeignKey(
        "NL2SQLFeedback",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promoted_examples",
        verbose_name="Aus Feedback promoted",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "aifw"
        db_table = "aifw_nl2sql_examples"
        verbose_name = "NL2SQL Beispiel"
        verbose_name_plural = "NL2SQL Beispiele"
        ordering = ["source", "difficulty", "id"]

    def __str__(self) -> str:
        return f"[{self.source.code}] {self.question[:60]}"


class NL2SQLFeedback(models.Model):
    """Auto-captured SQL errors + manual corrections.

    Lifecycle:
        1. NL2SQLEngine automatically creates a record on SQL execution error.
        2. Admin sets corrected_sql + marks promoted=True.
        3. promote_feedback command copies corrected entries to NL2SQLExample.
        4. Next prompts include the fix as a few-shot example.
    """

    ERROR_TYPE_CHOICES = [
        ("schema_error",  "Schema-Fehler (halluziniertes Feld)"),
        ("table_error",   "Tabellen-Fehler (halluzinierte Tabelle)"),
        ("join_error",    "Join-Fehler (falscher Join-Pfad)"),
        ("syntax_error",  "Syntax-Fehler"),
        ("timeout",       "Timeout"),
        ("unknown",       "Unbekannt"),
    ]

    source = models.ForeignKey(
        SchemaSource,
        on_delete=models.CASCADE,
        related_name="feedback",
        verbose_name="Schema Source",
    )
    question = models.TextField(verbose_name="Original-Frage")
    bad_sql = models.TextField(verbose_name="Fehlerhaftes SQL")
    error_message = models.TextField(verbose_name="Fehlermeldung")
    error_type = models.CharField(
        max_length=20,
        choices=ERROR_TYPE_CHOICES,
        default="unknown",
        verbose_name="Fehlertyp",
    )
    corrected_sql = models.TextField(
        blank=True,
        verbose_name="Korrigiertes SQL",
        help_text="Manuell korrigiertes SQL — wird beim Promote zu NL2SQLExample.",
    )
    promoted = models.BooleanField(
        default=False,
        verbose_name="Zu Example promoted",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "aifw"
        db_table = "aifw_nl2sql_feedback"
        verbose_name = "NL2SQL Feedback"
        verbose_name_plural = "NL2SQL Feedback"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.error_type}] {self.question[:60]} ({self.created_at:%Y-%m-%d})"

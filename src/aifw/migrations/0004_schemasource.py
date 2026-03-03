"""Migration 0004: SchemaSource für aifw.nl2sql."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0003_aiusagelog_tenant_object_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="SchemaSource",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        help_text="Eindeutiger Identifier, z.B. 'scm_manufacturing'.",
                        max_length=100,
                        unique=True,
                        verbose_name="Code",
                    ),
                ),
                ("name", models.CharField(max_length=200, verbose_name="Name")),
                (
                    "db_alias",
                    models.CharField(
                        default="default",
                        help_text="Django DATABASES-Alias. 'default' für Haupt-DB.",
                        max_length=100,
                        verbose_name="DB Alias",
                    ),
                ),
                (
                    "schema_xml",
                    models.TextField(
                        blank=True,
                        help_text=(
                            "Schema-Metadaten als XML. Beschreibt Tabellen, Spalten, "
                            "Beziehungen und Few-Shot-Beispiele für den LLM-Prompt."
                        ),
                        verbose_name="Schema XML",
                    ),
                ),
                (
                    "table_prefix",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "Erlaubter Tabellen-Prefix (z.B. 'scm_'). "
                            "Leer = alle Tabellen erlaubt."
                        ),
                        max_length=50,
                        verbose_name="Tabellen-Prefix",
                    ),
                ),
                (
                    "blocked_tables",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text=(
                            "Kommaseparierte Tabellennamen die nie abgefragt werden dürfen. "
                            "Intern werden auth_user, auth_token, django_session etc. immer ergänzt."
                        ),
                        verbose_name="Geblockte Tabellen",
                    ),
                ),
                (
                    "max_rows",
                    models.IntegerField(
                        default=500,
                        help_text="Maximale Ergebniszeilen.",
                        verbose_name="Max Zeilen",
                    ),
                ),
                (
                    "timeout_seconds",
                    models.IntegerField(
                        default=30,
                        help_text="Query-Timeout in Sekunden.",
                        verbose_name="Timeout (s)",
                    ),
                ),
                (
                    "allow_explain",
                    models.BooleanField(
                        default=False,
                        help_text="EXPLAIN ANALYZE für Debug-Zwecke erlauben.",
                        verbose_name="EXPLAIN erlauben",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Aktiv"),
                ),
            ],
            options={
                "verbose_name": "NL2SQL Schema Source",
                "verbose_name_plural": "NL2SQL Schema Sources",
                "db_table": "aifw_nl2sql_schema_sources",
                "ordering": ["code"],
            },
        ),
    ]

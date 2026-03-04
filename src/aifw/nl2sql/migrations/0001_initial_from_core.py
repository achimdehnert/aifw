"""
0001 — NL2SQL models transferred from app "aifw" → "aifw_nl2sql".

SeparateDatabaseAndState: NO DDL — tables already exist with correct names:
    aifw_nl2sql_schema_sources
    aifw_nl2sql_examples
    aifw_nl2sql_feedback

Django state is rebuilt here so aifw_nl2sql owns the models going forward.
All future NL2SQL migrations belong in this directory.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("aifw", "0007_nl2sql_app_label"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="SchemaSource",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                        ("code", models.CharField(max_length=100, unique=True, verbose_name="Code")),
                        ("name", models.CharField(max_length=200, verbose_name="Name")),
                        ("db_alias", models.CharField(default="default", max_length=100)),
                        ("schema_xml", models.TextField(blank=True, verbose_name="Schema XML")),
                        ("table_prefix", models.CharField(blank=True, max_length=50)),
                        ("blocked_tables", models.TextField(blank=True, default="")),
                        ("max_rows", models.IntegerField(default=500)),
                        ("timeout_seconds", models.IntegerField(default=30)),
                        ("allow_explain", models.BooleanField(default=False)),
                        ("is_active", models.BooleanField(default=True)),
                    ],
                    options={
                        "verbose_name": "NL2SQL Schema Source",
                        "verbose_name_plural": "NL2SQL Schema Sources",
                        "db_table": "aifw_nl2sql_schema_sources",
                        "ordering": ["code"],
                        "app_label": "aifw_nl2sql",
                    },
                ),
                migrations.CreateModel(
                    name="NL2SQLFeedback",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                        ("question", models.TextField(verbose_name="Original-Frage")),
                        ("bad_sql", models.TextField(verbose_name="Fehlerhaftes SQL")),
                        ("error_message", models.TextField(verbose_name="Fehlermeldung")),
                        (
                            "error_type",
                            models.CharField(
                                choices=[
                                    ("schema_error", "Schema-Fehler (halluziniertes Feld)"),
                                    ("table_error", "Tabellen-Fehler (halluzinierte Tabelle)"),
                                    ("join_error", "Join-Fehler (falscher Join-Pfad)"),
                                    ("syntax_error", "Syntax-Fehler"),
                                    ("timeout", "Timeout"),
                                    ("unknown", "Unbekannt"),
                                ],
                                default="unknown",
                                max_length=20,
                                verbose_name="Fehlertyp",
                            ),
                        ),
                        ("corrected_sql", models.TextField(blank=True, verbose_name="Korrigiertes SQL")),
                        ("promoted", models.BooleanField(default=False, verbose_name="Zu Example promoted")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "source",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="feedback",
                                to="aifw_nl2sql.schemasource",
                                verbose_name="Schema Source",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "NL2SQL Feedback",
                        "verbose_name_plural": "NL2SQL Feedback",
                        "db_table": "aifw_nl2sql_feedback",
                        "ordering": ["-created_at"],
                        "app_label": "aifw_nl2sql",
                    },
                ),
                migrations.CreateModel(
                    name="NL2SQLExample",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                        ("question", models.TextField(verbose_name="Frage")),
                        ("sql", models.TextField(verbose_name="Verifiziertes SQL")),
                        ("domain", models.CharField(blank=True, max_length=50, verbose_name="Domäne")),
                        ("difficulty", models.IntegerField(default=1, verbose_name="Schwierigkeitsgrad")),
                        ("is_active", models.BooleanField(default=True, verbose_name="Aktiv")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("verified_at", models.DateTimeField(blank=True, null=True)),
                        (
                            "source",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="examples",
                                to="aifw_nl2sql.schemasource",
                                verbose_name="Schema Source",
                            ),
                        ),
                        (
                            "promoted_from",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="promoted_examples",
                                to="aifw_nl2sql.nl2sqlfeedback",
                                verbose_name="Aus Feedback promoted",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "NL2SQL Beispiel",
                        "verbose_name_plural": "NL2SQL Beispiele",
                        "db_table": "aifw_nl2sql_examples",
                        "ordering": ["source", "difficulty", "id"],
                        "app_label": "aifw_nl2sql",
                    },
                ),
            ],
        ),
    ]

"""
0006 — NL2SQLExample + NL2SQLFeedback

NL2SQLExample:  Verified Q→SQL pairs for few-shot prompting.
NL2SQLFeedback: Auto-captured SQL errors + manual corrections pipeline.

Depends on 0005 (SchemaSource) which is in the installed whl (0.6.0).
We depend on 0004_schemasource here since that's what's in local migrations.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0005_quality_level_routing"),
    ]

    operations = [
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
                (
                    "corrected_sql",
                    models.TextField(
                        blank=True,
                        verbose_name="Korrigiertes SQL",
                    ),
                ),
                ("promoted", models.BooleanField(default=False, verbose_name="Zu Example promoted")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feedback",
                        to="aifw.schemasource",
                        verbose_name="Schema Source",
                    ),
                ),
            ],
            options={
                "verbose_name": "NL2SQL Feedback",
                "verbose_name_plural": "NL2SQL Feedback",
                "db_table": "aifw_nl2sql_feedback",
                "ordering": ["-created_at"],
                "app_label": "aifw",
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
                        to="aifw.schemasource",
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
                        to="aifw.nl2sqlfeedback",
                        verbose_name="Aus Feedback promoted",
                    ),
                ),
            ],
            options={
                "verbose_name": "NL2SQL Beispiel",
                "verbose_name_plural": "NL2SQL Beispiele",
                "db_table": "aifw_nl2sql_examples",
                "ordering": ["source", "difficulty", "id"],
                "app_label": "aifw",
            },
        ),
    ]

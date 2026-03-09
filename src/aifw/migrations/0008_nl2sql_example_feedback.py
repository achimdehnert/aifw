"""
0008 — NL2SQLExample + NL2SQLFeedback

NL2SQLExample:  Verified Q→SQL pairs for few-shot prompting.
NL2SQLFeedback: Auto-captured SQL errors + manual corrections pipeline.

Renamed from 0006 to resolve conflict with 0006_delete_schemasource migration.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0006_delete_schemasource_alter_aiactiontype_options_and_more"),
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
                "ordering": ["difficulty", "id"],
                "app_label": "aifw",
            },
        ),
    ]

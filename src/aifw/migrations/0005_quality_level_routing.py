"""
0005 — Quality level routing (ADR-095).

Adds quality_level / priority / prompt_template_key to AIActionType,
quality_level to AIUsageLog, and creates TierQualityMapping.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0004_schemasource"),
    ]

    operations = [
        # ── AIActionType: new routing fields ─────────────────────────────────
        migrations.AddField(
            model_name="aiactiontype",
            name="quality_level",
            field=models.IntegerField(
                null=True,
                blank=True,
                help_text=(
                    "Quality band (1-9) or NULL (catch-all). "
                    "1-3=Economy, 4-6=Balanced, 7-9=Premium."
                ),
            ),
        ),
        migrations.AddField(
            model_name="aiactiontype",
            name="priority",
            field=models.CharField(
                max_length=16,
                null=True,
                blank=True,
                help_text="'fast'|'balanced'|'quality' or NULL (catch-all).",
            ),
        ),
        migrations.AddField(
            model_name="aiactiontype",
            name="prompt_template_key",
            field=models.CharField(
                max_length=128,
                null=True,
                blank=True,
                help_text="promptfw template key or NULL.",
            ),
        ),
        # ── AIActionType: relax unique constraint on code ─────────────────────
        migrations.AlterField(
            model_name="aiactiontype",
            name="code",
            field=models.CharField(max_length=100, db_index=True),
        ),
        # ── AIUsageLog: quality_level column ─────────────────────────────────
        migrations.AddField(
            model_name="aiusagelog",
            name="quality_level",
            field=models.IntegerField(
                null=True,
                blank=True,
                db_index=True,
                help_text="Quality level of the request (1-9).",
            ),
        ),
        # ── TierQualityMapping model ──────────────────────────────────────────
        migrations.CreateModel(
            name="TierQualityMapping",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False
                )),
                ("tier", models.CharField(
                    max_length=64,
                    unique=True,
                    help_text="Subscription tier name e.g. 'premium'.",
                )),
                ("quality_level", models.IntegerField(
                    help_text="Quality level 1-9 assigned to this tier.",
                )),
                ("is_active", models.BooleanField(default=True, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Tier Quality Mapping",
                "verbose_name_plural": "Tier Quality Mappings",
                "ordering": ["-quality_level"],
                "app_label": "aifw",
            },
        ),
    ]

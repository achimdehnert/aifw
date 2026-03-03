"""
Migration 0005 — aifw 0.6.0 quality-level routing (ADR-095 / ADR-097).

Operations (in safe dependency order):
  1. AIActionType.code: unique → db_index (Breaking change — allows N rows/code)
  2. AIActionType: add quality_level, priority, prompt_template_key
  3. AIActionType: add DB CHECK constraint on priority
  4. AIActionType: add 4 partial unique indexes (PostgreSQL NULL semantics)
  5. AIActionType: add composite index (code, is_active)
  6. TierQualityMapping: new model
  7. TierQualityMapping: seed default rows (premium=8, pro=5, freemium=2)
  8. AIUsageLog: add quality_level column + index

All RunSQL operations include correct reverse_sql for ← migration support.
"""
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0005_merge_schemasource_alter"),
    ]

    operations = [
        # ── 1. Drop unique constraint on code, replace with index ──────────────────
        migrations.AlterField(
            model_name="aiactiontype",
            name="code",
            field=models.CharField(
                max_length=100,
                db_index=True,
                help_text="Action identifier. Multiple rows allowed per code "
                          "(quality_level / priority routing).",
            ),
        ),
        # ── 2. Add new columns to AIActionType ─────────────────────────────────
        migrations.AddField(
            model_name="aiactiontype",
            name="quality_level",
            field=models.IntegerField(
                null=True,
                blank=True,
                help_text="Quality band 1–9 or NULL (catch-all).",
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
        # ── 3. DB CHECK constraint on priority ────────────────────────────────
        migrations.RunSQL(
            sql=(
                "ALTER TABLE aifw_action_types "
                "ADD CONSTRAINT chk_aiaction_priority "
                "CHECK (priority IS NULL OR priority IN ('fast', 'balanced', 'quality'));"
            ),
            reverse_sql=(
                "ALTER TABLE aifw_action_types "
                "DROP CONSTRAINT IF EXISTS chk_aiaction_priority;"
            ),
        ),
        # ── 4. Four partial unique indexes (PostgreSQL NULL != NULL) ─────────────
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX uix_aiaction_exact "
                "ON aifw_action_types (code, quality_level, priority) "
                "WHERE quality_level IS NOT NULL AND priority IS NOT NULL;"
            ),
            reverse_sql="DROP INDEX IF EXISTS uix_aiaction_exact;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX uix_aiaction_ql_only "
                "ON aifw_action_types (code, quality_level) "
                "WHERE quality_level IS NOT NULL AND priority IS NULL;"
            ),
            reverse_sql="DROP INDEX IF EXISTS uix_aiaction_ql_only;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX uix_aiaction_prio_only "
                "ON aifw_action_types (code, priority) "
                "WHERE priority IS NOT NULL AND quality_level IS NULL;"
            ),
            reverse_sql="DROP INDEX IF EXISTS uix_aiaction_prio_only;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX uix_aiaction_catchall "
                "ON aifw_action_types (code) "
                "WHERE quality_level IS NULL AND priority IS NULL;"
            ),
            reverse_sql="DROP INDEX IF EXISTS uix_aiaction_catchall;",
        ),
        # ── 5. Composite index (code, is_active) for lookup queries ────────────
        migrations.AddIndex(
            model_name="aiactiontype",
            index=models.Index(
                fields=["code", "is_active"],
                name="idx_aiaction_code_active",
            ),
        ),
        # ── 6. New model: TierQualityMapping ─────────────────────────────────
        migrations.CreateModel(
            name="TierQualityMapping",
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
                    "tier",
                    models.CharField(
                        max_length=64,
                        unique=True,
                        help_text="Subscription tier name e.g. 'premium', 'pro', 'freemium'.",
                    ),
                ),
                (
                    "quality_level",
                    models.IntegerField(
                        help_text="Quality level 1–9 assigned to this tier.",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, db_index=True),
                ),
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
        # ── 7. Seed default TierQualityMapping rows ────────────────────────────
        migrations.RunSQL(
            sql="""
                INSERT INTO aifw_tierqualitymapping (tier, quality_level, is_active, created_at, updated_at)
                VALUES
                    ('premium',  8, TRUE, NOW(), NOW()),
                    ('pro',      5, TRUE, NOW(), NOW()),
                    ('freemium', 2, TRUE, NOW(), NOW())
                ON CONFLICT (tier) DO NOTHING;
            """,
            reverse_sql=(
                "DELETE FROM aifw_tierqualitymapping "
                "WHERE tier IN ('premium', 'pro', 'freemium');"
            ),
        ),
        # ── 8. AIUsageLog: quality_level column + index ────────────────────────
        migrations.AddField(
            model_name="aiusagelog",
            name="quality_level",
            field=models.IntegerField(
                null=True,
                blank=True,
                db_index=True,
                help_text=(
                    "Quality level of the request (1–9). "
                    "NULL for legacy entries created before 0.6.0."
                ),
            ),
        ),
        migrations.AddIndex(
            model_name="aiusagelog",
            index=models.Index(
                fields=["quality_level", "created_at"],
                name="idx_usagelog_ql_created",
            ),
        ),
    ]

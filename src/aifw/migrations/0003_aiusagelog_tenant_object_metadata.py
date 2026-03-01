"""
0003 — AIUsageLog: add tenant_id, object_id, metadata fields.

tenant_id:  UUID, nullable, indexed — multi-tenancy support
object_id:  CharField(200), blank, indexed — domain object reference
metadata:   JSONField(default=dict) — arbitrary context per LLM call
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0002_aiactiontype_budget_per_day"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiusagelog",
            name="tenant_id",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                help_text="Tenant UUID for multi-tenant applications.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="aiusagelog",
            name="object_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "Opaque reference to the domain object that triggered this call "
                    "(e.g. 'chapter:42', 'project:7'). Set by the consumer."
                ),
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="aiusagelog",
            name="metadata",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Arbitrary key/value context "
                    "(pipeline stage, prompt version, etc.)."
                ),
            ),
        ),
    ]

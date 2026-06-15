from django.db import migrations, models


class Migration(migrations.Migration):
    """Add AIUsageLog.privacy_mode (issue #8).

    Non-blocking for existing consumers: column defaults to 'full', so every
    pre-existing row keeps legacy raw-logging semantics with no data migration.
    """

    # NB: the real leaf of the aifw graph is 0007 (it depends on 0008, the
    # numbering is non-linear after the nl2sql app_label move). Depend on the
    # leaf, not the higher number, to avoid a multi-leaf conflict.
    dependencies = [
        ("aifw", "0007_nl2sql_app_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiusagelog",
            name="privacy_mode",
            field=models.CharField(
                db_index=True,
                default="full",
                help_text=(
                    "Privacy policy applied at write time: "
                    "'full' (raw) | 'pseudonymous' (HMAC user_hash + topic) | "
                    "'anonymous' (tenant + day_bucket only)."
                ),
                max_length=16,
            ),
        ),
    ]

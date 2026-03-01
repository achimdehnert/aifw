from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiactiontype",
            name="budget_per_day",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="Max USD spend per day. Switches to fallback model when exceeded.",
                max_digits=10,
                null=True,
            ),
        ),
    ]

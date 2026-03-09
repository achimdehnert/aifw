"""
0007 — NL2SQL models move from app_label "aifw" → "aifw_nl2sql".

SeparateDatabaseAndState: NO DDL — db_table is explicitly set on all models
and remains identical. Django state is updated to reflect the new app_label.

Prereq: "aifw.nl2sql" must be in INSTALLED_APPS before running this migration.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0008_nl2sql_example_feedback"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name="NL2SQLFeedback"),
                migrations.DeleteModel(name="NL2SQLExample"),
            ],
        ),
    ]

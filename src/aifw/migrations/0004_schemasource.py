"""
0004 — SchemaSource model (stub — applied via 0.6.0 whl on prod).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0003_aiusagelog_tenant_object_metadata"),
    ]

    operations = [
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
                "app_label": "aifw",
            },
        ),
    ]

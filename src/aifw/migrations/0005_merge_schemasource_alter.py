"""
Merge migration: resolves conflict between two parallel 0004 branches.

Branch A: 0004_schemasource          (SchemaSource model — nl2sql)
Branch B: 0004_alter_aiactiontype... (verbose_name + BigAutoField options)

Both depend on 0003. Neither modifies the same table.
Safe to merge: no schema conflicts, pure additive.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("aifw", "0004_schemasource"),
        ("aifw", "0004_alter_aiactiontype_options_alter_aiusagelog_options_and_more"),
    ]

    operations = []

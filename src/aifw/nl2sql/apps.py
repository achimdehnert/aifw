"""
aifw.nl2sql.apps — Django AppConfig for the optional NL2SQL component.

Activate by adding "aifw.nl2sql" to INSTALLED_APPS:
    INSTALLED_APPS = [
        "aifw",
        "aifw.nl2sql",   # ← enables NL2SQL models + migrations
    ]

Projects that don't need NL2SQL (travel-beat, writing-hub, weltenhub)
simply omit this entry — no tables are created, no overhead.
"""
from django.apps import AppConfig


class NL2SQLConfig(AppConfig):
    name = "aifw.nl2sql"
    label = "aifw_nl2sql"
    verbose_name = "aifw NL2SQL"
    default_auto_field = "django.db.models.BigAutoField"

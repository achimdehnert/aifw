from django.apps import AppConfig


class AifwConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "aifw"
    verbose_name = "AI Services"

    def ready(self) -> None:
        from aifw.signals import _connect_signals

        _connect_signals()

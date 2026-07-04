SECRET_KEY = "test-secret-key-aifw"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "aifw",
]

# promptfw is an optional extra ([promptfw], part of [dev]) — enable its
# Django app only when installed, so the DB-template resolution path
# (ADR-146) is exercised by tests without making promptfw a hard test dep.
try:
    import promptfw.contrib.django  # noqa: F401

    INSTALLED_APPS.append("promptfw.contrib.django")
except ImportError:  # pragma: no cover
    pass
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

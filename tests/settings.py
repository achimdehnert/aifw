SECRET_KEY = "test-secret-key-aifw"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "aifw",
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

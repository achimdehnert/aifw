import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LLMProvider",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=50, unique=True)),
                ("display_name", models.CharField(max_length=100)),
                ("api_key_env_var", models.CharField(default="", max_length=100)),
                ("base_url", models.URLField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"db_table": "aifw_llm_providers", "verbose_name": "LLM Provider"},
        ),
        migrations.CreateModel(
            name="LLMModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100)),
                ("display_name", models.CharField(max_length=100)),
                ("max_tokens", models.IntegerField(default=4096)),
                ("supports_vision", models.BooleanField(default=False)),
                ("supports_tools", models.BooleanField(default=True)),
                ("input_cost_per_million", models.DecimalField(decimal_places=4, default=0, max_digits=10)),
                ("output_cost_per_million", models.DecimalField(decimal_places=4, default=0, max_digits=10)),
                ("is_active", models.BooleanField(default=True)),
                ("is_default", models.BooleanField(default=False)),
                ("provider", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="models", to="aifw.llmprovider")),
            ],
            options={"db_table": "aifw_llm_models", "verbose_name": "LLM Model", "unique_together": {("provider", "name")}},
        ),
        migrations.CreateModel(
            name="AIActionType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=100, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("max_tokens", models.IntegerField(default=2000)),
                ("temperature", models.FloatField(default=0.7)),
                ("is_active", models.BooleanField(default=True)),
                ("default_model", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="default_for_actions", to="aifw.llmmodel")),
                ("fallback_model", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="fallback_for_actions", to="aifw.llmmodel")),
            ],
            options={"db_table": "aifw_action_types", "verbose_name": "AI Action Type"},
        ),
        migrations.CreateModel(
            name="AIUsageLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("input_tokens", models.IntegerField(default=0)),
                ("output_tokens", models.IntegerField(default=0)),
                ("total_tokens", models.IntegerField(default=0)),
                ("estimated_cost", models.DecimalField(decimal_places=6, default=0, max_digits=10)),
                ("latency_ms", models.IntegerField(default=0)),
                ("success", models.BooleanField(default=True)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("action_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="aifw.aiactiontype")),
                ("model_used", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="aifw.llmmodel")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "aifw_usage_logs", "verbose_name": "AI Usage Log", "ordering": ["-created_at"]},
        ),
    ]

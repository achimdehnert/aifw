"""Seed default LLM providers and models into the DB."""

from django.core.management.base import BaseCommand

from aifw.models import AIActionType, LLMModel, LLMProvider

PROVIDERS = [
    {"name": "anthropic", "display_name": "Anthropic", "api_key_env_var": "ANTHROPIC_API_KEY"},
    {"name": "openai", "display_name": "OpenAI", "api_key_env_var": "OPENAI_API_KEY"},
    {"name": "google", "display_name": "Google", "api_key_env_var": "GOOGLE_API_KEY"},
]

MODELS = [
    {
        "provider": "anthropic",
        "name": "claude-3-5-sonnet-20241022",
        "display_name": "Claude 3.5 Sonnet",
        "max_tokens": 8192,
        "supports_tools": True,
        "input_cost_per_million": 3.0,
        "output_cost_per_million": 15.0,
        "is_default": True,
    },
    {
        "provider": "anthropic",
        "name": "claude-3-haiku-20240307",
        "display_name": "Claude 3 Haiku",
        "max_tokens": 4096,
        "supports_tools": True,
        "input_cost_per_million": 0.25,
        "output_cost_per_million": 1.25,
    },
    {
        "provider": "openai",
        "name": "gpt-4o",
        "display_name": "GPT-4o",
        "max_tokens": 4096,
        "supports_tools": True,
        "input_cost_per_million": 5.0,
        "output_cost_per_million": 15.0,
    },
    {
        "provider": "openai",
        "name": "gpt-4o-mini",
        "display_name": "GPT-4o Mini",
        "max_tokens": 4096,
        "supports_tools": True,
        "input_cost_per_million": 0.15,
        "output_cost_per_million": 0.60,
    },
]


class Command(BaseCommand):
    help = "Seed default aifw LLM providers and models"

    def handle(self, *args, **options):
        for p in PROVIDERS:
            obj, created = LLMProvider.objects.get_or_create(
                name=p["name"], defaults=p
            )
            self.stdout.write(
                f"{'Created' if created else 'Exists'}: Provider {obj.display_name}"
            )

        for m in MODELS:
            provider = LLMProvider.objects.filter(name=m.pop("provider")).first()
            if not provider:
                continue
            obj, created = LLMModel.objects.get_or_create(
                provider=provider, name=m["name"], defaults={**m, "provider": provider}
            )
            self.stdout.write(
                f"{'Created' if created else 'Exists'}: Model {obj.display_name}"
            )

        self.stdout.write(self.style.SUCCESS("aifw config initialized."))

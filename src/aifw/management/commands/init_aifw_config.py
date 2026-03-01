"""
Seed default LLM providers and models into the DB.

This command seeds infrastructure-level data only: providers and models.
Domain-specific AIActionType entries (e.g. chapter_generation, travel_itinerary)
belong in each consumer app's own fixture or management command.

Usage:
    python manage.py init_aifw_config
"""

from django.core.management.base import BaseCommand

from aifw.models import LLMModel, LLMProvider

PROVIDERS = [
    {
        "name": "anthropic",
        "display_name": "Anthropic",
        "api_key_env_var": "ANTHROPIC_API_KEY",
    },
    {
        "name": "openai",
        "display_name": "OpenAI",
        "api_key_env_var": "OPENAI_API_KEY",
    },
    {
        "name": "google",
        "display_name": "Google",
        "api_key_env_var": "GOOGLE_API_KEY",
    },
    {
        "name": "ollama",
        "display_name": "Ollama (local)",
        "api_key_env_var": "",
        "base_url": "http://localhost:11434",
    },
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
    {
        "provider": "google",
        "name": "gemini/gemini-1.5-pro",
        "display_name": "Gemini 1.5 Pro",
        "max_tokens": 8192,
        "supports_tools": True,
        "input_cost_per_million": 3.5,
        "output_cost_per_million": 10.5,
    },
]


class Command(BaseCommand):
    help = "Seed default aifw LLM providers and models (no domain-specific actions)"

    def handle(self, *args, **options):
        for p in PROVIDERS:
            defaults = {k: v for k, v in p.items() if k != "name"}
            obj, created = LLMProvider.objects.get_or_create(
                name=p["name"], defaults=defaults
            )
            self.stdout.write(
                f"{'Created' if created else 'Exists'}: Provider {obj.display_name}"
            )

        for m in MODELS:
            provider = LLMProvider.objects.filter(name=m["provider"]).first()
            if not provider:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipped model {m['name']}: "
                        f"provider '{m['provider']}' not found"
                    )
                )
                continue
            defaults = {k: v for k, v in m.items() if k not in ("provider", "name")}
            defaults["provider"] = provider
            obj, created = LLMModel.objects.get_or_create(
                provider=provider, name=m["name"], defaults=defaults
            )
            self.stdout.write(
                f"{'Created' if created else 'Exists'}: Model {obj.display_name}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "aifw providers and models initialized.\n"
                "Tip: run your app-specific fixture to seed AIActionType entries."
            )
        )

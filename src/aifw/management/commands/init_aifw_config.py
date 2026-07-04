"""
Seed default LLM providers and models into the DB.

This command seeds infrastructure-level data: providers, models, and the
framework-owned ``nl2sql`` AIActionType (aifw.nl2sql is part of this package).
Domain-specific AIActionType entries (e.g. chapter_generation, travel_itinerary)
still belong in each consumer app's own fixture or management command.

Model routing follows the org LLM policy (Groq/Cerebras free tier first,
escalation to Claude Haiku 4.5 → Sonnet → Opus only when justified):

    Tier 1a  groq/llama-3.3-70b-versatile   (global default)
    Tier 1a  cerebras/gpt-oss-120b
    Tier 2   anthropic/claude-haiku-4-5     (nl2sql fallback)
    Tier 3   anthropic/claude-sonnet-5

If ``iil-promptfw`` (extra ``[promptfw]``) is installed, the NL2SQL system
prompt is additionally seeded as promptfw template ``nl2sql.system`` (ADR-146).

Idempotent: get_or_create everywhere — existing rows are never overwritten.
Known-dead upstream model IDs from earlier seeds are deactivated (see
DEAD_MODELS), so stale rows stop being routable without deleting usage history.

Usage:
    python manage.py init_aifw_config
"""

from django.core.management.base import BaseCommand

from aifw.models import AIActionType, LLMModel, LLMProvider

PROVIDERS = [
    {
        "name": "groq",
        "display_name": "Groq",
        "api_key_env_var": "GROQ_API_KEY",
    },
    {
        "name": "cerebras",
        "display_name": "Cerebras",
        "api_key_env_var": "CEREBRAS_API_KEY",
    },
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
    # litellm routes Google AI Studio via the "gemini/" prefix — a provider
    # named "google" produced the unroutable string "google/…" (see
    # _build_model_string in aifw.service). Fresh installs get "gemini".
    {
        "name": "gemini",
        "display_name": "Google Gemini",
        "api_key_env_var": "GEMINI_API_KEY",
    },
    {
        "name": "ollama",
        "display_name": "Ollama (local)",
        "api_key_env_var": "",
        "base_url": "http://localhost:11434",
    },
]

MODELS = [
    # ── Tier 1a: free tier first (org policy llm-routing) ────────────────────
    {
        "provider": "groq",
        "name": "llama-3.3-70b-versatile",
        "display_name": "Llama 3.3 70B Versatile (Groq)",
        "max_tokens": 32768,
        "supports_tools": True,
        "input_cost_per_million": 0.59,
        "output_cost_per_million": 0.79,
        "is_default": True,
    },
    {
        "provider": "cerebras",
        "name": "gpt-oss-120b",
        "display_name": "GPT-OSS 120B (Cerebras)",
        "max_tokens": 32768,
        "supports_tools": True,
        "input_cost_per_million": 0.35,
        "output_cost_per_million": 0.75,
    },
    # ── Tier 2/3: Anthropic escalation ───────────────────────────────────────
    {
        "provider": "anthropic",
        "name": "claude-haiku-4-5",
        "display_name": "Claude Haiku 4.5",
        "max_tokens": 64000,
        "supports_tools": True,
        "input_cost_per_million": 1.0,
        "output_cost_per_million": 5.0,
    },
    {
        "provider": "anthropic",
        "name": "claude-sonnet-5",
        "display_name": "Claude Sonnet 5",
        "max_tokens": 128000,
        "supports_tools": True,
        "input_cost_per_million": 3.0,
        "output_cost_per_million": 15.0,
    },
    # ── Optional non-default providers ───────────────────────────────────────
    {
        "provider": "openai",
        "name": "gpt-5.1",
        "display_name": "GPT-5.1",
        "max_tokens": 128000,
        "supports_tools": True,
        "input_cost_per_million": 1.25,
        "output_cost_per_million": 10.0,
    },
    {
        "provider": "openai",
        "name": "gpt-5-mini",
        "display_name": "GPT-5 Mini",
        "max_tokens": 128000,
        "supports_tools": True,
        "input_cost_per_million": 0.25,
        "output_cost_per_million": 2.0,
    },
    {
        "provider": "gemini",
        "name": "gemini-2.5-pro",
        "display_name": "Gemini 2.5 Pro",
        "max_tokens": 65535,
        "supports_tools": True,
        "input_cost_per_million": 1.25,
        "output_cost_per_million": 10.0,
    },
]

# Seeded by earlier aifw versions, retired upstream (checked against
# mcp-hub/docs/known-dead-models.txt + litellm model registry, 2026-07):
#   claude-3-5-sonnet-20241022  retired 2025-10-28 (→ claude-sonnet-5)
#   claude-3-haiku-20240307     retired 2026-04-19 (→ claude-haiku-4-5)
#   gemini/gemini-1.5-pro       retired upstream; string also routed as the
#                               invalid litellm prefix "google/gemini/…"
# gpt-4o / gpt-4o-mini are outdated but still served → replaced in the seed
# above, NOT deactivated in existing installs.
DEAD_MODELS = frozenset(
    {
        "claude-3-5-sonnet-20241022",
        "claude-3-haiku-20240307",
        "gemini/gemini-1.5-pro",
    }
)

# promptfw action_code of the NL2SQL system prompt (ADR-146).
NL2SQL_PROMPT_KEY = "nl2sql.system"


class Command(BaseCommand):
    help = "Seed default aifw LLM providers, models and the nl2sql action type"

    def handle(self, *args, **options):
        for p in PROVIDERS:
            defaults = {k: v for k, v in p.items() if k != "name"}
            obj, created = LLMProvider.objects.get_or_create(name=p["name"], defaults=defaults)
            self.stdout.write(f"{'Created' if created else 'Exists'}: Provider {obj.display_name}")

        for m in MODELS:
            provider = LLMProvider.objects.filter(name=m["provider"]).first()
            if not provider:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipped model {m['name']}: provider '{m['provider']}' not found"
                    )
                )
                continue
            defaults = {k: v for k, v in m.items() if k not in ("provider", "name")}
            defaults["provider"] = provider
            obj, created = LLMModel.objects.get_or_create(
                provider=provider, name=m["name"], defaults=defaults
            )
            self.stdout.write(f"{'Created' if created else 'Exists'}: Model {obj.display_name}")

        self._deactivate_dead_models()
        self._seed_nl2sql_action()
        self._seed_promptfw_template()

        self.stdout.write(
            self.style.SUCCESS(
                "aifw providers and models initialized.\n"
                "Tip: run your app-specific fixture to seed further "
                "AIActionType entries."
            )
        )

    def _deactivate_dead_models(self):
        """Deactivate models retired upstream (legacy seeds in existing DBs).

        Uses .save() per row (not queryset.update) so the config-cache
        invalidation signals fire.
        """
        for model in LLMModel.objects.filter(name__in=DEAD_MODELS, is_active=True):
            model.is_active = False
            model.is_default = False
            model.save(update_fields=["is_active", "is_default"])
            self.stdout.write(
                self.style.WARNING(
                    f"Deactivated dead model: {model.provider.name}/{model.name}"
                )
            )

    def _seed_nl2sql_action(self):
        """Seed the framework-owned nl2sql AIActionType (catch-all row).

        Groq free tier first (org policy), failover to Claude Haiku 4.5
        (Tier 2) via the existing default/fallback mechanism.
        """
        default_model = LLMModel.objects.filter(
            provider__name="groq", name="llama-3.3-70b-versatile"
        ).first()
        fallback_model = LLMModel.objects.filter(
            provider__name="anthropic", name="claude-haiku-4-5"
        ).first()
        if default_model is None:
            self.stdout.write(
                self.style.WARNING(
                    "  Skipped AIActionType nl2sql: groq default model not found"
                )
            )
            return
        obj, created = AIActionType.objects.get_or_create(
            code="nl2sql",
            quality_level=None,
            priority=None,
            defaults={
                "name": "NL2SQL Text-to-SQL",
                "description": (
                    "SQL-Generierung aus natuerlicher Sprache "
                    "(aifw.nl2sql.engine). Groq free-tier first, "
                    "Failover auf Claude Haiku 4.5."
                ),
                "default_model": default_model,
                "fallback_model": fallback_model,
                "max_tokens": 2000,
                "temperature": 0.05,
                "prompt_template_key": NL2SQL_PROMPT_KEY,
            },
        )
        self.stdout.write(
            f"{'Created' if created else 'Exists'}: AIActionType {obj.code} "
            f"(default={obj.default_model}, fallback={obj.fallback_model})"
        )

    def _seed_promptfw_template(self):
        """Seed the NL2SQL system prompt as promptfw template (ADR-146).

        Soft dependency: silently skipped when iil-promptfw (extra
        ``[promptfw]``) is not installed or its Django app is not migrated.
        """
        try:
            from promptfw.contrib.django.models import PromptTemplate
        except ImportError:
            self.stdout.write(
                "promptfw not installed — skipped template seed "
                f"({NL2SQL_PROMPT_KEY})."
            )
            return

        from aifw.nl2sql.engine import SYSTEM_PROMPT_TEMPLATE

        # Same content as the builtin fallback, converted to Jinja2 syntax.
        system_template = (
            SYSTEM_PROMPT_TEMPLATE.replace("{blocked_tables}", "{{ blocked_tables }}")
            .replace("{max_rows}", "{{ max_rows }}")
            .replace("{schema_xml}", "{{ schema_xml }}")
        )
        try:
            obj, created = PromptTemplate.objects.get_or_create(
                action_code=NL2SQL_PROMPT_KEY,
                version=1,
                defaults={
                    "name": "NL2SQL System Prompt",
                    "description": (
                        "System prompt of aifw.nl2sql.engine (ADR-146). "
                        "Content mirrors the builtin SYSTEM_PROMPT_TEMPLATE."
                    ),
                    "system_template": system_template,
                    "user_template": "{{ question }}",
                    "variables_schema": {
                        "blocked_tables": {"type": "string", "required": True},
                        "max_rows": {"type": "integer", "required": True},
                        "schema_xml": {"type": "string", "required": True},
                        "question": {"type": "string", "required": True},
                    },
                    "domain": "nl2sql",
                },
            )
        except Exception as e:  # e.g. promptfw app not in INSTALLED_APPS/migrated
            self.stdout.write(
                self.style.WARNING(f"  Skipped promptfw template seed: {e}")
            )
            return
        self.stdout.write(
            f"{'Created' if created else 'Exists'}: promptfw template "
            f"{NL2SQL_PROMPT_KEY}"
        )


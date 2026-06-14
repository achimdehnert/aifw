"""Tests for aifw.cost.estimate_cost()."""

from decimal import Decimal
from unittest.mock import patch

from aifw.cost import _FALLBACK_RATES, cost_from_rates, estimate_cost
from aifw.schema import LLMResult


class TestCostFromRates:
    """The single per-million arithmetic helper shared by estimate_cost and
    the usage-log path."""

    def test_should_compute_from_explicit_rates(self):
        # 1000 * 3.0/1M + 500 * 15.0/1M = 0.003 + 0.0075 = 0.0105
        assert cost_from_rates(1000, 500, 3.0, 15.0) == Decimal("0.0105")

    def test_should_return_decimal_for_db_decimal_rates(self):
        assert cost_from_rates(1000, 1000, Decimal("0.15"), Decimal("0.60")) == Decimal("0.00075")

    def test_should_return_zero_for_zero_rates(self):
        assert cost_from_rates(1000, 1000, 0, 0) == Decimal("0")

    def test_should_never_raise_on_bad_input(self):
        assert cost_from_rates(1000, 500, None, None) == Decimal("0")


class TestFallbackTableHygiene:
    def test_should_not_contain_bogus_claude_snapshot_id(self):
        """The placeholder 'claude-sonnet-4-5-20250514' must stay removed."""
        assert "claude-sonnet-4-5-20250514" not in _FALLBACK_RATES

    def test_fallback_ids_are_unique_and_real_shaped(self):
        for key in _FALLBACK_RATES:
            assert "/" not in key  # bare model id, provider prefix stripped at lookup


class TestEstimateCostStandalone:
    """Test estimate_cost() with explicit parameters."""

    def test_should_return_zero_for_empty_model(self):
        assert estimate_cost(model="", input_tokens=100, output_tokens=100) == Decimal("0")

    def test_should_return_zero_for_zero_tokens(self):
        assert estimate_cost(model="gpt-4o", input_tokens=0, output_tokens=0) == Decimal("0")

    def test_should_estimate_with_fallback_rates(self):
        """When litellm.cost_per_token raises, fallback table is used."""
        with patch("aifw.cost.litellm") as mock_ll:
            mock_ll.cost_per_token.side_effect = Exception("not found")
            cost = estimate_cost(model="gpt-4o-mini", input_tokens=1000, output_tokens=500)
            # 1000 * 0.15/1M + 500 * 0.60/1M = 0.00015 + 0.0003 = 0.00045
            assert cost > Decimal("0")
            assert cost < Decimal("0.001")

    def test_should_use_litellm_when_available(self):
        with patch("aifw.cost.litellm") as mock_ll:
            mock_ll.cost_per_token.return_value = (0.001, 0.002)
            cost = estimate_cost(model="gpt-4o", input_tokens=1000, output_tokens=500)
            assert cost == Decimal("0.003")
            mock_ll.cost_per_token.assert_called_once_with(
                model="gpt-4o",
                prompt_tokens=1000,
                completion_tokens=500,
            )

    def test_should_handle_provider_prefix_in_model(self):
        """Model names like 'groq/llama-3.3-70b-versatile' should match fallback table."""
        with patch("aifw.cost.litellm") as mock_ll:
            mock_ll.cost_per_token.side_effect = Exception("not found")
            cost = estimate_cost(
                model="groq/llama-3.3-70b-versatile",
                input_tokens=10000,
                output_tokens=5000,
            )
            assert cost > Decimal("0")

    def test_should_return_default_rate_for_unknown_model(self):
        with patch("aifw.cost.litellm") as mock_ll:
            mock_ll.cost_per_token.side_effect = Exception("not found")
            cost = estimate_cost(model="unknown-model", input_tokens=1000, output_tokens=1000)
            # Uses default (0.15, 0.60) rates
            assert cost > Decimal("0")


class TestEstimateCostFromResult:
    """Test estimate_cost() with LLMResult."""

    def test_should_estimate_from_result(self):
        result = LLMResult(
            success=True,
            model="gpt-4o-mini",
            input_tokens=1000,
            output_tokens=500,
        )
        with patch("aifw.cost.litellm") as mock_ll:
            mock_ll.cost_per_token.return_value = (0.00015, 0.0003)
            cost = estimate_cost(result)
            assert cost > Decimal("0")

    def test_should_prefer_explicit_model_over_result(self):
        result = LLMResult(success=True, model="gpt-4o", input_tokens=100, output_tokens=100)
        with patch("aifw.cost.litellm") as mock_ll:
            mock_ll.cost_per_token.return_value = (0.001, 0.002)
            estimate_cost(result, model="gpt-4o-mini")
            mock_ll.cost_per_token.assert_called_once_with(
                model="gpt-4o-mini",
                prompt_tokens=100,
                completion_tokens=100,
            )


class TestLLMResultMethod:
    """Test LLMResult.estimate_cost() method."""

    def test_should_delegate_to_cost_module(self):
        result = LLMResult(
            success=True,
            model="gpt-4o-mini",
            input_tokens=1000,
            output_tokens=500,
        )
        with patch("aifw.cost.litellm") as mock_ll:
            mock_ll.cost_per_token.return_value = (0.00015, 0.0003)
            cost = result.estimate_cost()
            assert isinstance(cost, Decimal)
            assert cost > Decimal("0")

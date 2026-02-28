"""
aifw — Django AI Services Framework

DB-driven LLM provider, model & usage management for Django projects.
"""

__version__ = "0.1.0"

from aifw.schema import LLMResult, ToolCall

__all__ = ["LLMResult", "ToolCall", "__version__"]

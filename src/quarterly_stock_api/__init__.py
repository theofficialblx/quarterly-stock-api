"""Reusable stock-price and macroeconomic calendar-quarter alignment."""

from .core import MergeResult, MergeValidationError, merge_quarterly_data

__all__ = ["MergeResult", "MergeValidationError", "merge_quarterly_data"]
__version__ = "1.0.0"

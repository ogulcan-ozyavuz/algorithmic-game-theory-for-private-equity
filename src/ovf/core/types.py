"""
Core domain types and financial numeric primitives for OVF.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Common numerical aliases
Numeric = int | float | Decimal


class SeniorityOrder(StrEnum):
    STANDARD = "standard"  # Higher tier / newer round pays first
    PARI_PASSU = "pari_passu"  # Same priority, pro-rata sharing
    TIERED = "tiered"  # Explicit integer priority


class WaterfallType(StrEnum):
    EUROPEAN = "european"  # Whole-of-fund
    AMERICAN = "american"  # Deal-by-deal


class HurdleType(StrEnum):
    SOFT = "soft"  # Full catch-up once hurdle is cleared
    HARD = "hard"  # Carry only on gains above hurdle
    NONE = "none"  # No hurdle


# Pydantic annotated types for validation
Money = Annotated[float, Field(ge=0.0, description="Monetary value in base currency (e.g., USD)")]
ShareCount = Annotated[float, Field(ge=0.0, description="Number of shares")]
SharePrice = Annotated[float, Field(ge=0.0, description="Price per share")]
Percentage = Annotated[
    float, Field(ge=0.0, le=1.0, description="Normalized proportion between 0.0 and 1.0")
]
Multiple = Annotated[float, Field(ge=0.0, description="Multiple (e.g. 1.0x, 2.0x)")]
Seniority = Annotated[
    int, Field(ge=0, description="Seniority rank (0 = highest priority, or ascending)")
]


class FinancialBaseModel(BaseModel):
    """Validated finite numeric values; float inputs use a single base currency."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        validate_default=True,
        allow_inf_nan=False,
        extra="forbid",
    )

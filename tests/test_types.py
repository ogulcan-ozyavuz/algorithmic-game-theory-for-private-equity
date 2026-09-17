"""
Unit tests for ovf.core.types.
"""

import pytest
from pydantic import ValidationError

from ovf.core.types import (
    FinancialBaseModel,
    HurdleType,
    Money,
    Multiple,
    Percentage,
    SeniorityOrder,
    WaterfallType,
)


class DummyFinancialModel(FinancialBaseModel):
    amount: Money
    percentage: Percentage
    multiple: Multiple


def test_valid_financial_types():
    model = DummyFinancialModel(amount=1000.50, percentage=0.25, multiple=2.0)
    assert model.amount == 1000.50
    assert model.percentage == 0.25
    assert model.multiple == 2.0


def test_invalid_negative_money():
    with pytest.raises(ValidationError):
        DummyFinancialModel(amount=-10.0, percentage=0.5, multiple=1.0)


def test_invalid_percentage_bounds():
    with pytest.raises(ValidationError):
        DummyFinancialModel(amount=10.0, percentage=1.5, multiple=1.0)
    with pytest.raises(ValidationError):
        DummyFinancialModel(amount=10.0, percentage=-0.1, multiple=1.0)


def test_enums():
    assert SeniorityOrder.STANDARD == "standard"
    assert SeniorityOrder.PARI_PASSU == "pari_passu"
    assert WaterfallType.EUROPEAN == "european"
    assert WaterfallType.AMERICAN == "american"
    assert HurdleType.SOFT == "soft"
    assert HurdleType.HARD == "hard"

"""Cap table snapshots; calculation is delegated to ovf.waterfall."""

from __future__ import annotations

import math
from datetime import date
from typing import Self

from pydantic import Field, model_validator

from ovf.contracts.securities import PreferredStock, Security
from ovf.core.types import FinancialBaseModel, Percentage, ShareCount
from ovf.waterfall import Payout as Payout
from ovf.waterfall import WaterfallResult, solve_waterfall, validate_securities


class CapTable(FinancialBaseModel):
    securities: list[Security] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        validate_securities(self.securities)
        return self

    def add(self, security: Security) -> CapTable:
        validate_securities([*self.securities, security])
        self.securities.append(security)
        return self

    @property
    def total_shares(self) -> ShareCount:
        """Issued shares plus reserved capacity; excludes unresolved SAFE dilution."""
        validate_securities(self.securities)
        return math.fsum(s.shares for s in self.securities)

    @property
    def fully_diluted_shares(self) -> ShareCount:
        """Issued and as-converted shares, refusing anything whose count is undetermined.

        The test is structural and fails safe, rather than being a list of known types.
        A security is refused when it can still turn into shares but holds none yet: a
        SAFE, or a convertible note whose exit treatment has not been stated. Counting
        such an instrument as zero would report its holder at 0% and everyone else too
        high, with no error. The earlier guard was a list of two SAFE classes and it
        failed exactly as a list does, the moment two more SAFE forms were added in a
        module this one does not own.

        An instrument that has already been resolved is allowed and contributes what it
        actually holds: a note settled to repay becomes cash, not shares, and a term loan
        never converts. A new money-denominated type that cannot prove it is resolved is
        refused rather than silently counted as zero.
        """
        validate_securities(self.securities)
        undetermined = sorted(
            s.security_id
            for s in self.securities
            if s.is_convertible() and s.shares <= 0 and getattr(s, "exit_treatment", None) is None
        )
        if undetermined:
            raise ValueError(
                "Resolve SAFEs and other unresolved convertible instruments before "
                "computing fully diluted ownership. These can still convert into shares "
                f"but hold none yet, so the total is undefined: {', '.join(undetermined)}."
            )
        return math.fsum(
            s.converted_shares if isinstance(s, PreferredStock) else s.shares
            for s in self.securities
        )

    def ownership_breakdown(self) -> dict[str, Percentage]:
        total = self.fully_diluted_shares
        result: dict[str, float] = {}
        if total:
            for s in self.securities:
                shares = s.converted_shares if isinstance(s, PreferredStock) else s.shares
                result[s.holder_id] = result.get(s.holder_id, 0.0) + shares / total
        return result

    def waterfall(
        self,
        exit_valuation: float,
        transaction_costs: float = 0.0,
        max_iterations: int = 20,
        *,
        as_of: date | None = None,
    ) -> list[Payout]:
        """Compatibility list API; raises if the supported allocation cannot be verified."""
        return self.waterfall_detailed(
            exit_valuation, transaction_costs, max_iterations, as_of=as_of
        ).payouts

    def waterfall_detailed(
        self,
        exit_valuation: float,
        transaction_costs: float = 0.0,
        max_iterations: int = 20,
        *,
        as_of: date | None = None,
    ) -> WaterfallResult:
        """Allocation, convergence diagnostics and a reproducible input fingerprint.

        ``as_of`` is the explicit settlement date used to accrue any debt on the table.
        It is required whenever the table holds a debt instrument, and is never defaulted
        to the current date: an implicit clock would make the result irreproducible.
        """
        return solve_waterfall(
            self.securities, exit_valuation, transaction_costs, max_iterations, as_of=as_of
        )

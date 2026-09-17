"""An exact rational oracle enumerates all strategies on small cap tables.

The oracle prices residual participation with capped per-share cash levels, rather
than calling any production allocation function. It validates this finite model,
not universal equilibrium existence or legal contract interpretation.
"""

from fractions import Fraction
from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import ovf


def exact_payoffs(common_shares, terms, exit_value, state):
    # terms: (shares, price, seniority, liquidation_multiple, participating, cap)
    result = [Fraction(0) for _ in terms]
    cash = Fraction(exit_value)
    for rank in sorted({t[2] for t in terms}):
        claims = {
            i: Fraction(t[0] * t[1] * t[3])
            for i, t in enumerate(terms)
            if t[2] == rank and not state[i]
        }
        total = sum(claims.values(), Fraction(0))
        paid = min(cash, total)
        for i, claim in claims.items():
            result[i] += paid * claim / total if total else 0
        cash -= paid
    units = {-1: Fraction(common_shares)}
    limits = {}
    for i, t in enumerate(terms):
        if state[i] or t[4]:
            units[i] = Fraction(t[0])
            if not state[i] and t[4] and t[5] is not None:
                limits[i] = Fraction(t[0] * t[1] * t[5]) - result[i]
    thresholds = sorted({Fraction(0), *(limits[i] / units[i] for i in limits)})
    for level in thresholds:
        clipped = {i for i in limits if limits[i] / units[i] <= level}
        rate = (cash - sum((limits[i] for i in clipped), Fraction(0))) / sum(
            (u for i, u in units.items() if i not in clipped), Fraction(0)
        )
        if rate >= level and all(rate * units[i] <= limits[i] for i in limits if i not in clipped):
            common_cash = rate * units[-1]
            for i in range(len(terms)):
                if i in units:
                    result[i] += min(rate * units[i], limits[i]) if i in limits else rate * units[i]
            return [common_cash, *result]
    raise AssertionError("No oracle residual price")


term = st.tuples(
    st.integers(1, 8),
    st.integers(1, 5),
    st.integers(1, 3),
    st.integers(1, 2),
    st.booleans(),
    st.booleans(),
)


@given(st.integers(1, 20), st.lists(term, min_size=1, max_size=3), st.integers(0, 250))
@settings(max_examples=100, derandomize=True, deadline=None)
def test_matches_exact_equilibrium_set(common_shares, raw_terms, exit_value):
    terms = [
        (n, price, rank, lp, part, lp + 1 if part and capped else None)
        for n, price, rank, lp, part, capped in raw_terms
    ]
    table = ovf.CapTable().add(ovf.common(common_shares))
    for i, (n, price, rank, lp, part, cap) in enumerate(terms):
        table.add(
            ovf.preferred(
                n,
                price,
                seniority=rank,
                liquidation_multiple=lp,
                participating=part,
                participation_cap=cap,
                holder_id=f"p{i}",
            )
        )
    payoffs = {
        state: exact_payoffs(common_shares, terms, exit_value, state)
        for state in product([False, True], repeat=len(terms))
    }
    equilibria = {
        state: amounts
        for state, amounts in payoffs.items()
        if all(
            amounts[i + 1]
            >= payoffs[tuple(not a if j == i else a for j, a in enumerate(state))][i + 1]
            for i in range(len(terms))
        )
    }
    report = table.waterfall_detailed(exit_value)
    actual_state = tuple(p.converted for p in report.payouts[1:])
    assert actual_state in equilibria
    assert [p.amount for p in report.payouts] == pytest.approx(
        [float(x) for x in equilibria[actual_state]]
    )
    assert sum(p.amount for p in report.payouts) == pytest.approx(exit_value)
    # Record insertion order must not affect the chosen state or amounts.
    reversed_result = ovf.CapTable(securities=list(reversed(table.securities))).waterfall(
        exit_value
    )
    assert {p.security_id: p.amount for p in reversed_result} == pytest.approx(
        {p.security_id: p.amount for p in report.payouts}
    )

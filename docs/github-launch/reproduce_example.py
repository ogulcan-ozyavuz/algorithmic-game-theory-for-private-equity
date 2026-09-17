"""Reproduce the launch draft's illustrative game and export its figure and data.

Run from the repository root after installing the checkout and matplotlib:
    python docs/github-launch/reproduce_example.py

This is one specified example, not a general analytical-breakpoint algorithm.
The source implementation is read; no package source or existing README is edited.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
from fractions import Fraction
from itertools import product
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import equilibria as eq
from ovf.waterfall import evaluate_fixed_waterfall

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "assets"


def make_table() -> eq.CapTable:
    return eq.CapTable(
        securities=[
            eq.common(8_000_000, holder_id="founders", security_id="common"),
            eq.preferred(
                2_000_000,
                2.50,
                seniority=2,
                participating=True,
                participation_cap=2.0,
                holder_id="series_a",
                security_id="series_a",
            ),
            eq.preferred(
                1_500_000,
                6.00,
                seniority=1,
                holder_id="series_b",
                security_id="series_b",
            ),
        ]
    )


def expected_millions(exit_m: Fraction) -> tuple[Fraction, Fraction, Fraction]:
    """Hand-derived equilibrium cash curves for this three-position example only."""
    x = exit_m
    zero = Fraction(0)
    if x <= 9:
        return zero, zero, x
    if x <= 14:
        return zero, x - 9, Fraction(9)
    if x <= 39:
        return 4 * (x - 14) / 5, 5 + (x - 14) / 5, Fraction(9)
    if x <= 59:
        return x - 19, Fraction(10), Fraction(9)
    if x <= 69:
        return 4 * (x - 9) / 5, (x - 9) / 5, Fraction(9)
    return 16 * x / 23, 4 * x / 23, 3 * x / 23


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    table = make_table()
    rows = []
    max_error = 0.0
    for k in range(1001):
        x = Fraction(k, 10)
        result = table.waterfall_detailed(float(x) * 1_000_000)
        expected = expected_millions(x)
        for payout, exact in zip(result.payouts, expected, strict=True):
            error = abs(payout.amount - float(exact) * 1_000_000)
            max_error = max(max_error, error)
            assert error <= result.tolerance
        assert result.max_unilateral_gain <= result.tolerance
        assert abs(result.conservation_error) <= result.tolerance
        assert abs(result.conservation_error) <= 1e-6
        rows.append(
            [
                float(x),
                *[p.amount / 1_000_000 for p in result.payouts],
                *[p.converted for p in result.payouts[1:]],
            ]
        )
    with (OUT / "exit-payoff-curves.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "exit_m",
                "common_m",
                "series_a_m",
                "series_b_m",
                "series_a_converts",
                "series_b_converts",
            ]
        )
        writer.writerows(rows)

    # Rational values below are derived directly in the accompanying README example.
    expected_matrix = {
        (False, False): (Fraction(41), Fraction(10), Fraction(9)),
        (False, True): (Fraction(800, 19), Fraction(10), Fraction(150, 19)),
        (True, False): (Fraction(204, 5), Fraction(51, 5), Fraction(9)),
        (True, True): (Fraction(960, 23), Fraction(240, 23), Fraction(180, 23)),
    }
    matrix = []
    for a, b in product((False, True), repeat=2):
        payouts, remaining = evaluate_fixed_waterfall(
            table.securities, 60_000_000, {"series_a": a, "series_b": b}
        )
        assert remaining == 0
        for sec, exact in zip(table.securities, expected_matrix[(a, b)], strict=True):
            assert math.isclose(
                payouts[sec.security_id].amount / 1_000_000, float(exact), rel_tol=1e-12
            )
        matrix.append(
            {
                "series_a_converts": a,
                "series_b_converts": b,
                "payouts_m": {k: p.amount / 1_000_000 for k, p in payouts.items()},
            }
        )
    survey = eq.enumerate_equilibria(table.securities, 60_000_000)
    assert survey.feasible_equilibria == [{"series_a": True, "series_b": False}]
    assert survey.payoff_unique
    report = table.waterfall_detailed(60_000_000)
    source_hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "src").rglob("*.py"))
    }
    data = {
        "purpose": "Illustrative launch example; generated scenario, not observed transaction",
        "python": platform.python_version(),
        "engine_version": report.engine_version,
        "grid_points": len(rows),
        "max_cash_error_against_piecewise_formula": max_error,
        "example_report": report.model_dump(mode="json"),
        "payoff_matrix": matrix,
        "equilibrium_survey": survey.model_dump(mode="json"),
        "source_sha256": source_hashes,
    }
    (OUT / "example-validation.json").write_text(json.dumps(data, indent=2) + "\n")

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
            "text.parse_math": False,
        }
    )
    values = np.array([r[:4] for r in rows])
    fig, (ax, decisions) = plt.subplots(
        2,
        1,
        figsize=(11, 7.4),
        gridspec_kw={"height_ratios": [4.5, 1]},
        sharex=True,
        layout="constrained",
    )
    fig.set_facecolor("white")
    colors = ["#153A5B", "#16857B", "#BA7134"]
    for col, label, color in zip(
        range(1, 4), ["Common", "Series A", "Series B"], colors, strict=True
    ):
        ax.plot(values[:, 0], values[:, col], color=color, label=label, linewidth=2.7)
    ax.set_title(
        "One preference stack. Three different cash-flow claims.",
        loc="left",
        fontsize=17,
        fontweight="bold",
        pad=18,
    )
    ax.set_ylabel("Exit proceeds allocated ($M)")
    ax.set_ylim(0, 73)
    ax.set_xlim(0, 100)
    ax.grid(axis="y", color="#E5E9ED", linewidth=0.8)
    ax.legend(loc="upper left", frameon=False, ncols=3)
    for knot, label, y in [
        (14, "Common starts\nreceiving cash", 28),
        (39, "A reaches its\nparticipation cap", 42),
        (59, "A's conversion\nindifference point", 55),
        (69, "B's conversion\nindifference point", 66),
    ]:
        ax.axvline(knot, color="#ADB8C1", linewidth=0.8, linestyle=(0, (3, 4)), zorder=0)
        ax.text(knot + 1.0, y, label, fontsize=8.7, color="#566471")
    for value, color in [(40.8, colors[0]), (10.2, colors[1]), (9, colors[2])]:
        ax.scatter([60], [value], color=color, s=26, zorder=4)
    ax.annotate(
        "At $60M: common $40.8M; A $10.2M; B $9M",
        xy=(60, 40.8),
        xytext=(27, 62),
        fontsize=10,
        color="#153A5B",
        arrowprops={"arrowstyle": "-", "color": "#153A5B", "lw": 0.8},
    )
    for y, boundary, color in [(1, 59, colors[1]), (0, 69, colors[2])]:
        decisions.broken_barh([(0, boundary)], (y - 0.28, 0.56), facecolors="#E9EEF2")
        decisions.broken_barh([(boundary, 100 - boundary)], (y - 0.28, 0.56), facecolors=color)
        decisions.text(boundary / 2, y, "Retain preference", va="center", ha="center", fontsize=10)
        decisions.text(
            (100 + boundary) / 2, y, "Convert", va="center", ha="center", fontsize=10, color="white"
        )
    decisions.set_yticks([0, 1], ["Series B", "Series A"])
    decisions.set_xlabel("Company exit proceeds ($M); zero debt and transaction costs")
    decisions.set_ylim(-0.7, 1.7)
    decisions.spines["left"].set_visible(False)
    decisions.tick_params(axis="y", length=0)
    decisions.set_xticks([0, 14, 39, 59, 69, 100])
    fig.get_layout_engine().set(rect=(0, 0.075, 1, 0.925))
    fig.text(
        0.012,
        0.012,
        "Illustrative terms: 8M common; A 2M shares / $5M invested / 1x participating, 2x cap; "
        "senior B 1.5M shares / $9M / 1x non-participating.\n"
        "Ties retain the incumbent action. Curves cross-checked against hand-derived formulas; "
        "this is not a valuation opinion.",
        fontsize=8,
        color="#566471",
    )
    fig.savefig(OUT / "exit-payoff-curves.svg", metadata={"Date": None})
    fig.savefig(OUT / "exit-payoff-curves.png", dpi=180)
    plt.close(fig)
    print(
        f"Verified {len(rows)} exit values, all four profiles at $60M, and the equilibrium survey."
    )
    print(f"Maximum cash error versus piecewise formulas: {max_error:.3g}")
    print("Artifacts: docs/github-launch/assets/")


if __name__ == "__main__":
    main()

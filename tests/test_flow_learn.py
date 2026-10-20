"""Median flow learning ignores outliers and waits for enough runs."""

from __future__ import annotations

import pytest

from sprinklecast.flow_learn import (
    FLOW_HISTORY_LIMIT,
    accept_sample,
    append_flow_history,
    compare_to_reference,
    reference_flow,
    robust_gpm,
    run_status,
    trend_status,
)


def _learn(values: list[float]) -> list[float]:
    samples: list[float] = []
    for gpm in values:
        samples = accept_sample(samples, gpm, minimum_runs=3)
    return samples


def test_alerts_wait_until_three_runs_then_use_thirty_and_twenty_five() -> None:
    samples: list[float] = []
    for gpm in (10.0, 10.0, 12.0):
        assert (
            run_status(gpm, samples, high_pct=30, low_pct=25, minimum_runs=3)
            == "learning"
        )
        samples = accept_sample(samples, gpm, minimum_runs=3)
    assert robust_gpm(samples) == 10.0
    assert run_status(13.0, samples, high_pct=30, low_pct=25, minimum_runs=3) == "ok"
    assert run_status(13.1, samples, high_pct=30, low_pct=25, minimum_runs=3) == "high_flow"
    assert run_status(7.5, samples, high_pct=30, low_pct=25, minimum_runs=3) == "ok"
    assert run_status(7.4, samples, high_pct=30, low_pct=25, minimum_runs=3) == "low_flow"


def test_an_outlier_is_reported_and_left_out_of_the_median() -> None:
    samples = _learn([10.0, 10.0, 10.0, 11.0])
    assert run_status(30.0, samples, high_pct=30, low_pct=25, minimum_runs=3) == "high_flow"
    kept = accept_sample(samples, 30.0, minimum_runs=3)
    assert kept == samples
    assert robust_gpm(kept) == 10.0


def test_a_saved_baseline_is_the_reference_and_learned_is_the_fallback() -> None:
    assert reference_flow({"baseline_gpm": 8.5, "baseline_source": "catch_cup"}) == (
        8.5,
        "catch_cup",
    )
    assert reference_flow({"learned_gpm": 4.0}) == (4.0, "learned")
    assert reference_flow({}) == (None, "none")
    assert compare_to_reference(11.2, 10.0, high_pct=30, low_pct=25) == "ok"
    assert compare_to_reference(13.1, 10.0, high_pct=30, low_pct=25) == "high_flow"
    assert compare_to_reference(7.4, 10.0, high_pct=30, low_pct=25) == "low_flow"


def test_trend_uses_the_median_of_the_last_five_and_history_keeps_thirty() -> None:
    history = [{"gpm": 10.0, "at": "t", "minutes": 15}]
    assert trend_status(history, 10.0, runs=5, trend_pct=10)[0] == "learning"
    drifted = history + [{"gpm": 11.2, "at": "t", "minutes": 10}] * 4
    status, drift = trend_status(drifted, 10.0, runs=5, trend_pct=10)
    assert status == "high_trend"
    assert drift == pytest.approx(12.0)
    flat = [{"gpm": 10.0, "at": "t", "minutes": 10}] * 5
    assert trend_status(flat, 10.0, runs=5, trend_pct=10)[0] == "ok"
    long = append_flow_history([], at="t", gpm=1, minutes=1)
    for index in range(40):
        long = append_flow_history(long, at="t", gpm=index + 1, minutes=1)
    assert len(long) == FLOW_HISTORY_LIMIT
    assert long[0]["gpm"] == 11

"""Median flow learning ignores outliers and waits for enough runs."""

from __future__ import annotations

from sprinklecast.flow_learn import accept_sample, robust_gpm, run_status


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

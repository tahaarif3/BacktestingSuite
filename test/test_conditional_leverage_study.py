import pandas as pd

from studies.run_spy_conditional_leverage_validation import monthly_targets


def test_month_end_signal_is_held_until_next_month_end():
    index = pd.bdate_range("2024-01-02", "2024-03-29")
    raw = pd.Series(1.0, index=index)
    raw.loc["2024-01-31"] = 1.25
    raw.loc["2024-02-29"] = 0.75

    target = monthly_targets(raw)

    assert target.loc["2024-01-30"] == 1.0
    assert target.loc["2024-01-31"] == 1.25
    assert target.loc["2024-02-28"] == 1.25
    assert target.loc["2024-02-29"] == 0.75
    assert target.loc["2024-03-08"] == 0.75

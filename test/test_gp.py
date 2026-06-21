import os
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from domain.models import Bar
from strat.genetic_programming import GeneticProgrammingStrategy

def test_gp_strategy_initialization():
    # Verify it raises FileNotFoundError for missing JSON path
    with pytest.raises(FileNotFoundError):
        GeneticProgrammingStrategy("missing_file.json")

    # Assuming champion_gp.json is present in the workspace
    if os.path.exists("champion_gp.json"):
        strat = GeneticProgrammingStrategy("champion_gp.json")
        assert len(strat.tree) > 0
        assert strat.volatility_threshold == 0.0035
        assert strat.deadband == 0.15

def test_gp_strategy_signal_generation():
    if not os.path.exists("champion_gp.json"):
        pytest.skip("champion_gp.json not found in workspace")

    strat = GeneticProgrammingStrategy("champion_gp.json")
    
    # Generate 100 mock bars to satisfy warm-up length (60)
    dates = pd.date_range(start="2020-01-01", periods=100)
    bars = [
        Bar(d, 100.0, 101.0, 99.0, 100.0, 1000.0) for d in dates
    ]
    
    signals = strat.generate_signals(bars)
    
    assert len(signals) == 100
    # First 60 elements should be 0.0 due to warm-up
    assert all(sig == 0.0 for sig in signals[:60])
    
    # Check that signals list contains floats
    assert all(isinstance(sig, float) for sig in signals)

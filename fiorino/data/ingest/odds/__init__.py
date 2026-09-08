"""
Odds feeds -> odds_snapshots.

The poller schedule is denser near kickoff (the last hour carries most of
the information). Coverage is asserted by v_data_coverage: a period with
thin snapshots produces a backtest that only saw the easy fixtures.
"""

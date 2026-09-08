"""
Signal generation. Reads exclusively through PointInTimeView.

A strategy proposes candidates (fixture, market, line, selection, price,
book, probability). It does NOT decide stake size — that is the allocator's
job, because sizing requires a portfolio-level view the strategy cannot see.
"""

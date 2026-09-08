"""
Point-in-time feature computation -> feature_values.

Every value carries the as_of instant at which it became computable from
already-settled information. Leakage here is undetectable downstream.
"""

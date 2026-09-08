"""
penaltyblog wrapped behind fiorino's own interfaces.

penaltyblog.py — adapts DixonColes/BivariatePoisson/etc. to the
                 GoalModel protocol, and handles what the library does not:
                 unseen (promoted) teams get a league-level prior instead of
                 the ValueError penaltyblog raises.
"""

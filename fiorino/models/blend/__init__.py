"""
Market blending and calibration.

blend.py       — combines model and market in logit space,
                 logit(p) = w*logit(p_model) + (1-w)*logit(p_market),
                 with w fitted out-of-fold. w is usually small: the market
                 is the stronger forecaster and the blend should admit it.
calibration.py — isotonic / Platt / temperature scaling, fitted out-of-fold.
"""

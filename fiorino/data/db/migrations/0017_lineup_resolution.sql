-- 0017_lineup_resolution — how precisely we know when an eleven became known.
--
-- lineups.published_at is filled by the recorder with the instant OUR poll
-- first saw a confirmed eleven. That is an upper bound, not a publication:
-- the eleven was public at or before it. The bound is safe — a fact stamped
-- later than it truly became knowable cannot leak backwards — but only if its
-- WIDTH travels with it, because the question the column exists for is what
-- the market did in the minutes after the eleven appeared, and a bound fifteen
-- minutes wide cannot answer a question about a fifteen-minute window.
--
-- NULL is not "precise". It is the case where no earlier poll covered the
-- match, so the eleven may have been public for hours before anyone looked.
-- The view below therefore excludes NULL rather than treating it as zero.
ALTER TABLE lineups ADD COLUMN known_at_uncertainty_seconds DOUBLE;

-- Only elevens whose instant is known precisely enough to be worth using, on
-- top of the identity discipline v_analytic_lineups already applies.
--
-- 900 seconds is not a law of nature; it is the widest bound that still leaves
-- a confirmed eleven distinguishable from the hour before it. Anything wider
-- and the event and its control window fall in the same cell, which is the
-- exact defect that made the BeatTheBookie hourly grid useless.
CREATE OR REPLACE VIEW v_resolved_lineups AS
SELECT l.*,
       l.known_at_uncertainty_seconds <= 900 AS resolves_quarter_hour
FROM v_analytic_lineups l
WHERE l.known_at_uncertainty_seconds IS NOT NULL;

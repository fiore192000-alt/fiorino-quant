"""
The end-to-end point-in-time chain audit.

Everything before this checked one link. M1's guard checks that a reader cannot
see a result before it settles. M5's check verifies no fit was trained through
its own kickoff. M6's verifies no blend weight consumed a match past its
boundary. Each is correct and each is local.

This walks the whole chain for a placed bet: every fact that informed it, the
instant it was taken, the kickoff, and the settlement — and asserts they are
ordered. A system can pass every local check and still be incoherent end to
end, because the links are verified against different clocks.

    fact_1 ─┐
    fact_2 ─┼─→ decision ──→ kickoff ──→ settlement
    fact_n ─┘
            every fact strictly before the decision it informed

ON THE ORDER OF LINEUPS AND DECISIONS
-------------------------------------
The M6.5 brief states the chain as

    decision_time < formation_time < kickoff < settlement_time

which is correct for a strategy that does NOT read lineups — and forbids the
one the milestone is for. If the decision precedes publication, the lineup
cannot have informed it.

The general invariant is the one implemented here: **every fact used by a
decision precedes that decision**. It yields two admissible orderings,

    lineup-blind    decision < published_at < kickoff       (lineup unused)
    lineup-informed published_at <= decision < kickoff      (lineup used)

and the audit checks the second only for decisions that declare a lineup as an
input. Hard-coding the brief's ordering would have made the experiment
impossible to run and the audit would have said everything was fine.
"""

from __future__ import annotations

from fiorino.data.identity.audit import BLOCKING, WARNING, Finding

__all__ = ["run_pit_chain_audit", "PIT_CHAIN_CHECKS"]


def _count(con, sql, params=None) -> int:
    row = con.execute(sql, params or []).fetchone()
    return row[0] if row and row[0] is not None else 0


# -- links in the chain ----------------------------------------------------


def check_decision_precedes_kickoff(con) -> list[Finding]:
    """A bet struck at or after the kickoff it bets on."""
    n = _count(con, """
        SELECT count(*) FROM bets b
        JOIN v_analytic_matches m ON m.match_id = b.match_id
        WHERE b.placed_at IS NOT NULL AND b.placed_at >= m.kickoff_utc
    """)
    return [Finding("decision_after_kickoff", BLOCKING,
                    f"{n} bets were placed at or after their own kickoff", n)] if n else []


def check_kickoff_precedes_settlement(con) -> list[Finding]:
    """A result that settled before the match started."""
    n = _count(con, """
        SELECT count(*) FROM match_results r
        JOIN matches m ON m.match_id = r.match_id
        WHERE r.settled_at < m.kickoff_utc
    """)
    return [Finding("settlement_before_kickoff", BLOCKING,
                    f"{n} results settled before their kickoff", n)] if n else []


def check_timestamped_price_precedes_decision(con) -> list[Finding]:
    """A bet struck on a price that did not exist yet.

    Only TIMESTAMPED prices can be checked: a PREMATCH price carries no instant
    by design, and inventing one to check it would defeat the purpose of not
    having invented one to store it. Those are covered by the kickoff bound
    instead, which is the strongest claim the data supports.
    """
    n = _count(con, """
        SELECT count(*) FROM bets b
        JOIN odds_observations o
          ON  o.match_id    = b.match_id
          AND o.bookmaker_id = b.bookmaker_id
          AND o.market_type = b.market_type
          AND o.line        = b.line
          AND o.selection   = b.selection
          AND o.price_decimal = b.price_taken
        WHERE b.price_precision = 'TIMESTAMPED'
          AND o.capture_precision = 'TIMESTAMPED'
          AND b.placed_at IS NOT NULL
          AND o.captured_at > b.placed_at
    """)
    return [Finding("price_after_decision", BLOCKING,
                    f"{n} bets used a price captured after the bet", n)] if n else []


def check_fit_precedes_decision(con) -> list[Finding]:
    """A bet informed by a model fitted after the bet was struck."""
    n = _count(con, """
        SELECT count(*) FROM bets b
        JOIN predictions p ON p.match_id = b.match_id
                          AND p.market_type = b.market_type
                          AND p.line = b.line
                          AND p.selection = b.selection
        JOIN model_runs r ON r.model_run_id = p.model_run_id
        WHERE b.placed_at IS NOT NULL AND r.trained_through > b.placed_at
          AND b.model_prob IS NOT NULL
          AND abs(p.prob_win - b.model_prob) < 1e-12
    """)
    return [Finding("fit_after_decision", BLOCKING,
                    f"{n} bets used a fit trained after the bet", n)] if n else []


def check_weight_precedes_its_boundary(con) -> list[Finding]:
    """M6's audit, folded into the chain so one call covers everything."""
    n = _count(con, "SELECT count(*) FROM v_weight_leakage")
    return [Finding("weight_trained_past_boundary", BLOCKING,
                    f"{n} ensemble weights consumed a match past their boundary", n)] if n else []


def check_lineup_precedes_kickoff(con) -> list[Finding]:
    """A confirmed eleven published at or after the kickoff.

    Not necessarily corrupt data — a source may back-fill after the match — but
    such a row can never inform a decision, and counting it as available is how
    a lineup study quietly becomes a post-hoc study.
    """
    n = _count(con, """
        SELECT count(*) FROM v_analytic_lineups l
        JOIN matches m ON m.match_id = l.match_id
        WHERE l.published_at >= m.kickoff_utc
    """)
    return [Finding("lineup_published_after_kickoff", WARNING,
                    f"{n} confirmed lineups were published at or after kickoff "
                    f"and cannot inform any decision", n)] if n else []


def check_lineup_informed_bets(con) -> list[Finding]:
    """The ordering that matters for M6.5.

    A bet declaring a lineup as an input must have been struck at or after that
    lineup was published. This is the check the brief's stated ordering would
    have inverted.
    """
    if not _count(con, """SELECT count(*) FROM duckdb_tables()
                          WHERE table_name = 'bet_lineup_inputs'"""):
        return []
    n = _count(con, """
        SELECT count(*) FROM bet_lineup_inputs i
        JOIN bets b   ON b.bet_id = i.bet_id
        JOIN lineups l ON l.lineup_id = i.lineup_id
        WHERE b.placed_at IS NOT NULL AND l.published_at > b.placed_at
    """)
    return [Finding("bet_used_unpublished_lineup", BLOCKING,
                    f"{n} bets declared a lineup published after the bet", n)] if n else []


def check_timestamped_coverage(con) -> list[Finding]:
    """Reports how much of the chain is actually checkable.

    With no TIMESTAMPED prices most links above are vacuously satisfied. An
    audit that returns "all clean" over an empty set is the most dangerous
    output this module can produce, so it says so out loud.
    """
    total = _count(con, "SELECT count(*) FROM odds_observations")
    stamped = _count(con, """SELECT count(*) FROM odds_observations
                             WHERE capture_precision = 'TIMESTAMPED'""")
    lineups = _count(con, "SELECT count(*) FROM lineups")
    if total and not stamped:
        return [Finding("no_timestamped_odds", WARNING,
                        f"0 of {total} odds observations are TIMESTAMPED: the "
                        f"price-before-decision link is untested, not proven",
                        total)]
    if not lineups:
        return [Finding("no_lineups", WARNING,
                        "no lineups ingested: the lineup links are untested", 0)]
    return []


PIT_CHAIN_CHECKS = (
    check_decision_precedes_kickoff,
    check_kickoff_precedes_settlement,
    check_timestamped_price_precedes_decision,
    check_fit_precedes_decision,
    check_weight_precedes_its_boundary,
    check_lineup_precedes_kickoff,
    check_lineup_informed_bets,
    check_timestamped_coverage,
)


def run_pit_chain_audit(con) -> list[Finding]:
    """Every link, in one call. Findings are returned, never raised."""
    findings = []
    for check in PIT_CHAIN_CHECKS:
        findings.extend(check(con))
    return findings

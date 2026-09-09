"""
The lineup recorder, and the four ways a first sighting turns into a lie.

The recorder is the only component in this project whose output cannot be
recomputed later: a poll not made is a fact lost for good. So the fold from
polls to sightings is tested harder than its size suggests, because a bug here
is discovered months after it has silently corrupted the only copy.
"""

from datetime import datetime, timedelta, timezone

import pytest

from fiorino.data.ingest.lineups.recorder import (
    CONFIRMED, PREDICTED, Lineup, Poll, deserialise, fold_sightings, serialise,
)

T0 = datetime(2026, 9, 10, 17, 0, tzinfo=timezone.utc)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def poll(minutes, lineups=(), scope=("m1",), error=None, source="test"):
    return Poll(source=source, observed_at=at(minutes), scope=tuple(scope),
                lineups=tuple(lineups), error=error)


def eleven(match="m1", team="home", status=CONFIRMED, players=("a", "b")):
    return Lineup(match_key=match, team=team, status=status, players=tuple(players))


class TestKnownAtIsOurClock:
    def test_the_first_confirmed_sighting_sets_known_at(self):
        [s] = fold_sightings([poll(0), poll(15, [eleven()])])
        assert s.known_at == at(15)

    def test_a_later_identical_sighting_does_not_move_it(self):
        [s] = fold_sightings([poll(0), poll(15, [eleven()]), poll(30, [eleven()])])
        assert s.known_at == at(15)
        assert s.superseded_by == []

    def test_a_predicted_eleven_never_sets_known_at(self):
        """The failure that would be invisible: predicted elevens are
        published hours earlier, so taking one would move the instant back and
        turn a real market move into a non-event."""
        sightings = fold_sightings([
            poll(0, [eleven(status=PREDICTED, players=("x", "y"))]),
            poll(120, [eleven()]),
        ])
        assert len(sightings) == 1
        assert sightings[0].known_at == at(120)
        assert sightings[0].status == CONFIRMED

    def test_a_stream_with_only_predictions_yields_nothing(self):
        assert fold_sightings([poll(0, [eleven(status=PREDICTED)])]) == []


class TestTheUncertaintyIsMeasuredNotDeclared:
    def test_it_is_the_gap_back_to_the_previous_successful_poll(self):
        [s] = fold_sightings([poll(0), poll(15, [eleven()])])
        assert s.known_at_uncertainty_seconds == 15 * 60

    def test_a_failed_poll_closes_no_gap(self):
        """Not looking and looking without success are the same evidence:
        none. Counting a failure would halve a real uncertainty."""
        [s] = fold_sightings([
            poll(0), poll(10, error="HTTP 503"), poll(20, [eleven()]),
        ])
        assert s.known_at_uncertainty_seconds == 20 * 60

    def test_a_poll_that_did_not_cover_the_match_closes_no_gap(self):
        """A poll scoped to tomorrow's fixtures says nothing about today's."""
        [s] = fold_sightings([
            poll(0, scope=("m1",)),
            poll(10, scope=("m2",)),
            poll(20, [eleven()], scope=("m1",)),
        ])
        assert s.known_at_uncertainty_seconds == 20 * 60

    def test_a_first_ever_poll_has_unknown_uncertainty(self):
        """No earlier poll means the eleven may have been public for hours.
        None, not zero — zero would be the most confident possible claim from
        the least evidence."""
        [s] = fold_sightings([poll(0, [eleven()])])
        assert s.known_at_uncertainty_seconds is None

    def test_an_unknown_uncertainty_is_never_usable(self):
        [s] = fold_sightings([poll(0, [eleven()])])
        assert not s.usable_for_window(3600)

    def test_a_sighting_is_usable_only_within_its_own_resolution(self):
        [s] = fold_sightings([poll(0), poll(15, [eleven()])])
        assert not s.usable_for_window(600)
        assert s.usable_for_window(900)


class TestRevisionsAreKeptNotOverwritten:
    def test_a_changed_eleven_is_recorded_beside_the_first(self):
        """Teams do republish — a withdrawal in the warm-up. The first
        sighting stays the answer to 'when did this become knowable'."""
        [s] = fold_sightings([
            poll(0), poll(15, [eleven()]),
            poll(40, [eleven(players=("a", "c"))]),
        ])
        assert s.known_at == at(15)
        assert len(s.superseded_by) == 1
        assert s.superseded_by[0]["players"] == ["a", "c"]

    def test_players_in_a_different_order_are_the_same_eleven(self):
        [s] = fold_sightings([
            poll(0), poll(15, [eleven(players=("a", "b"))]),
            poll(40, [eleven(players=("b", "a"))]),
        ])
        assert s.superseded_by == []


class TestTheArchiveRoundTrips:
    @pytest.mark.parametrize("original", [
        poll(0),
        poll(5, error="timeout"),
        poll(15, [eleven(), eleven(team="away", players=("c",))], scope=("m1", "m2")),
    ])
    def test_a_poll_survives_a_write_and_a_read(self, original):
        back = deserialise(serialise(original))
        assert back == original

    def test_the_line_carries_no_newline(self):
        assert "\n" not in serialise(poll(15, [eleven()]))

    def test_an_archive_read_back_folds_to_the_same_sightings(self):
        polls = [poll(0), poll(15, [eleven()])]
        lines = [serialise(p) for p in polls]
        assert fold_sightings([deserialise(x) for x in lines]) == fold_sightings(polls)

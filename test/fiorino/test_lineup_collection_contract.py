"""
The collector's operational contract.

The recorder's logic is tested in test_lineup_recorder.py. What is tested here
is everything around it that decides whether the collection actually happens:
a workflow that fails silently, an archive path swallowed by .gitignore, or a
run that errors out when the token is missing all produce the same outcome —
months with no data and nobody noticing until the day someone looks.

That failure mode is why this file exists, and why .gitignore is checked with
git itself rather than by reading the file: the last time a pattern swallowed
source in this repository, reading it was exactly what failed to catch it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/record-lineups.yml"
RUNNER = REPO / "scripts/record_lineups.py"
ARCHIVE = REPO / "archive/lineups"


class TestTheCollectionCanActuallyStart:
    def test_a_missing_token_is_not_an_error(self):
        """A workflow that fails every ten minutes until configured is a
        workflow people mute, and a muted collector is a stopped collector."""
        env = dict(os.environ)
        env.pop("SPORTMONKS_TOKEN", None)
        done = subprocess.run([sys.executable, str(RUNNER)], capture_output=True,
                              text=True, cwd=REPO, env=env, timeout=120)
        assert done.returncode == 0, done.stderr[-400:]
        assert "SPORTMONKS_TOKEN" in done.stdout

    def test_a_missing_token_writes_nothing(self):
        env = dict(os.environ)
        env.pop("SPORTMONKS_TOKEN", None)
        before = sorted(p.name for p in ARCHIVE.rglob("*.jsonl"))
        subprocess.run([sys.executable, str(RUNNER)], capture_output=True,
                       text=True, cwd=REPO, env=env, timeout=120)
        assert sorted(p.name for p in ARCHIVE.rglob("*.jsonl")) == before

    def test_the_archive_directory_is_tracked_by_git(self):
        """An archive git ignores is an archive that never leaves the runner."""
        probe = ARCHIVE / "2026" / "01" / "01.jsonl"
        done = subprocess.run(["git", "check-ignore", "-q", str(probe)],
                              cwd=REPO, capture_output=True)
        assert done.returncode != 0, f"{probe} e ignorato da git"


@pytest.fixture(scope="module")
def workflow():
    return WORKFLOW.read_text()


class TestTheWorkflowDoesNotLoseObservations:
    def test_it_is_scheduled(self, workflow):
        assert "schedule:" in workflow and "cron:" in workflow

    def test_concurrent_runs_are_queued_and_never_cancelled(self, workflow):
        """A cancelled run is an observation that will not exist again."""
        assert "cancel-in-progress: false" in workflow

    def test_it_rebases_instead_of_forcing(self, workflow):
        """Two polls can land together. A force push would drop one of them —
        which is the one failure this archive cannot absorb."""
        assert "--rebase" in workflow
        assert "--force" not in workflow

    def test_it_can_write_back(self, workflow):
        assert "contents: write" in workflow


class TestTheAdapterDoesNotInventFacts:
    def test_a_partial_eleven_is_not_recorded_as_confirmed(self):
        """A response delivering four starters is a partial response, not a
        small team. Recording it would set known_at on a fact that had not
        finished appearing."""
        from fiorino.data.ingest.lineups.sources.sportmonks import _lineups_from_fixture

        rows = [{"type_id": 11, "team_id": 1, "player_id": n} for n in range(4)]
        assert _lineups_from_fixture({"id": 9, "lineups": rows}) == []

    def test_a_full_eleven_is_recorded(self):
        from fiorino.data.ingest.lineups.sources.sportmonks import _lineups_from_fixture

        rows = [{"type_id": 11, "team_id": 1, "player_id": n} for n in range(11)]
        [lineup] = _lineups_from_fixture({"id": 9, "lineups": rows})
        assert lineup.status == "CONFIRMED"
        assert len(lineup.players) == 11

    def test_a_player_id_of_zero_is_a_player(self):
        """The bug this test was written after: `row.get("player_id") or ...`
        drops id 0, leaving ten starters, which the completeness guard then
        discards as a partial response. The eleven would never be recorded and
        nothing would say why."""
        from fiorino.data.ingest.lineups.sources.sportmonks import _lineups_from_fixture

        rows = [{"type_id": 11, "team_id": 0, "player_id": n} for n in range(11)]
        [lineup] = _lineups_from_fixture({"id": 9, "lineups": rows})
        assert len(lineup.players) == 11

    def test_bench_rows_do_not_count_towards_the_eleven(self):
        from fiorino.data.ingest.lineups.sources.sportmonks import _lineups_from_fixture

        rows = ([{"type_id": 11, "team_id": 1, "player_id": n} for n in range(10)]
                + [{"type_id": 12, "team_id": 1, "player_id": 99}])
        assert _lineups_from_fixture({"id": 9, "lineups": rows}) == []

    def test_a_failed_call_is_a_poll_with_an_error_not_an_exception(self):
        """A failure that raises is a poll that never gets written, and an
        unwritten failed poll silently narrows the next uncertainty."""
        from fiorino.data.ingest.lineups.sources import sportmonks

        poll = sportmonks.fetch("not-a-real-token", "2026-09-10")
        assert not poll.succeeded
        assert poll.lineups == ()


class TestTheVerifyIsDiagnosticsOnly:
    """The verify exists to be pasted into a conversation and read. What it
    must never do is write, invent, or leak."""

    def test_predicted_is_never_reported_as_a_count(self):
        """0 PREDICTED and PREDICTED not asked for are different facts. The
        adapter reads only starter rows, so a zero here would claim it looked."""
        source = (REPO / "scripts/record_lineups.py").read_text()
        assert "PREDICTED=UNSUPPORTED_BY_ADAPTER" in source
        assert "PREDICTED={" not in source
        assert "PREDICTED=0" not in source

    def test_the_uncertainty_is_not_simulated(self):
        """It is None at the first sighting because there is no previous poll
        to measure back to. A number here would be invented, and it is the one
        number the whole method rests on."""
        source = (REPO / "scripts/record_lineups.py").read_text()
        assert "KNOWN_AT_UNCERTAINTY_SECONDS=None" in source

    def test_the_token_is_redacted(self):
        """The error body is where a token leaks: providers echo the request
        back. The verify output is meant to be pasted somewhere."""
        from fiorino.data.ingest.lineups.sources.sportmonks import redact

        leaked = "GET /v3/football/fixtures?api_token=s3cr3t failed"
        assert "s3cr3t" not in redact(leaked, "s3cr3t")
        assert "***REDACTED***" in redact(leaked, "s3cr3t")

    def test_redaction_is_safe_when_there_is_no_token(self):
        from fiorino.data.ingest.lineups.sources.sportmonks import redact

        assert redact("qualcosa", "") == "qualcosa"

    def test_the_probe_never_touches_the_collection_path(self):
        """Diagnostics and collection share no code. Nothing printed by verify
        can become an archived record."""
        import inspect

        from fiorino.data.ingest.lineups.sources import sportmonks

        body = inspect.getsource(sportmonks.probe)
        assert "Poll(" not in body
        assert "fetch(" not in body

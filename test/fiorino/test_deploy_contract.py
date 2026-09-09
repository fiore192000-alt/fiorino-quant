"""
What a fresh deployment needs, asserted rather than hoped.

Every check here corresponds to something that actually broke when the app was
installed into a clean virtualenv from requirements.txt alone. None of them was
visible from the development tree, which is the point: the suite runs from the
repository root, where imports resolve from the working directory and every
dependency is already present.

The four failures, in the order they appeared:
  1. `import penaltyblog` — the repository's own package directory shadows the
     installed one and its Cython extensions are not built in a clone.
  2. `pytz` missing — DuckDB needs it for timezone functions, and pandas 3.0
     dropped it as a transitive dependency.
  3. bronze immutability — the app wrote to a fixed path and died on reload.
  4. the de-vig fallback collided on a primary key, and before that it was
     non-deterministic.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "app"


def _requirements() -> list[str]:
    lines = (REPO / "requirements.txt").read_text().splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


class TestRequirements:
    def test_the_runtime_dependencies_are_declared(self):
        names = {re.split(r"[<>=\[]", r)[0].lower() for r in _requirements()}
        for needed in ("streamlit", "duckdb", "pytz"):
            assert needed in names, f"{needed} missing from requirements.txt"

    def test_pytz_is_declared_explicitly(self):
        """It was transitive through pandas until pandas 3.0 dropped it, and
        DuckDB's timezone path fails with a bare ModuleNotFoundError."""
        assert "pytz" in {re.split(r"[<>=\[]", r)[0].lower() for r in _requirements()}

    def test_penaltyblog_is_not_a_requirement(self):
        """Installing it would be shadowed by the repository's own directory,
        which is uncompiled in a clone. The app does not need it."""
        assert "penaltyblog" not in {
            re.split(r"[<>=\[]", r)[0].lower() for r in _requirements()}


class TestTheAppDoesNotNeedPenaltyblog:
    def test_no_app_module_imports_it(self):
        for path in APP.rglob("*.py"):
            text = path.read_text()
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(("import penaltyblog", "from penaltyblog")):
                    pytest.fail(f"{path.relative_to(REPO)}: {stripped}")

    def test_the_app_imports_in_a_subprocess_without_it(self):
        """A real import, in a fresh interpreter, with penaltyblog blocked."""
        code = (
            "import sys\n"
            "class Block:\n"
            "    def find_module(self, name, path=None):\n"
            "        return self if name.split('.')[0] == 'penaltyblog' else None\n"
            "    def load_module(self, name):\n"
            "        raise ImportError(name)\n"
            "sys.meta_path.insert(0, Block())\n"
            f"sys.path.insert(0, {str(REPO)!r})\n"
            "import app.lib, fiorino.decision, fiorino.data.quality.pit_chain\n"
            "assert not [m for m in sys.modules if m.startswith('penaltyblog')]\n"
            "print('OK')\n"
        )
        done = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, cwd=REPO, timeout=180)
        assert done.returncode == 0, done.stderr[-1500:]
        assert "OK" in done.stdout


class TestTheAppNeverWritesToAFixedPath:
    def test_the_lake_root_is_unique_per_build(self):
        """Bronze is immutable by design, so a fixed path makes the second
        load raise FileExistsError. The app died on reload."""
        text = (APP / "lib.py").read_text()
        assert "mkdtemp" in text
        assert "/tmp/fiorino-app-lake" not in text


class TestNoSecretsOrLocalPaths:
    def test_the_app_carries_no_credentials(self):
        pattern = re.compile(r"(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}",
                             re.I)
        for path in APP.rglob("*.py"):
            assert not pattern.search(path.read_text()), path

    def test_the_app_requires_no_file_outside_the_repository(self):
        """Community Cloud has no $FIORINO_DATA_ROOT. Anything the app needs
        must be in the clone or fetched at runtime."""
        # Naming the variable in prose is fine and useful — explaining WHY the
        # warehouse is built at runtime is exactly what the docstring should
        # do. What must not happen is READING it.
        uses = re.compile(r"(os\.environ|getenv|data_root\s*\()")
        for path in APP.rglob("*.py"):
            for line in path.read_text().splitlines():
                code = line.split("#", 1)[0]
                if uses.search(code):
                    pytest.fail(f"{path.relative_to(REPO)}: reads the environment: {line.strip()}")
                if "/home/" in code or "/Users/" in code:
                    pytest.fail(f"{path.relative_to(REPO)}: absolute path: {line.strip()}")

    def test_the_entrypoint_exists_where_the_docs_say(self):
        assert (APP / "streamlit_app.py").exists()
        assert (REPO / "docs/architecture/webapp.md").read_text().count(
            "app/streamlit_app.py") >= 1

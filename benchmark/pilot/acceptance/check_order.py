import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class OrderTest(unittest.TestCase):
    def test_commands_are_stable_and_sorted(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            (repo / "README.md").write_text("pytest -q\npip list\npython -V\nnpm run build\nnpm run lint\n")
            (repo / "compose.yml").write_text("services: {}")
            (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "-q"\n[tool.ruff]\nline-length = 88\n')
            script = 'import json, sys; from src.analyze_repo import analyze; print(json.dumps(analyze(sys.argv[1])["commands"]))'
            results = []
            for seed in ("1", "2", "3", "4", "5"):
                env = {"PATH": os.environ["PATH"], "PYTHONHASHSEED": seed}
                output = subprocess.check_output([sys.executable, "-c", script, folder], cwd="/workspace", env=env, text=True)
                results.append(json.loads(output))
            self.assertTrue(all(result == results[0] for result in results))
            for commands in results[0].values():
                self.assertEqual(commands, sorted(commands))

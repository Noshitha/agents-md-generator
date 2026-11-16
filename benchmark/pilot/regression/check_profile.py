import tempfile
import unittest
from pathlib import Path

from src.analyze_repo import analyze


class ProfileTest(unittest.TestCase):
    def test_empty_repository_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = analyze(folder)
            self.assertEqual(profile["repo_name"], Path(folder).name)
            self.assertEqual(profile["top_level_dirs"], [])
            self.assertEqual(profile["top_level_files"], [])
            self.assertEqual(profile["commands"], {"backend": [], "frontend": [], "docker": [], "pyproject": []})
            self.assertEqual(profile["inferred_risks"], [])
            self.assertEqual(profile["summary"], {"has_backend": False, "has_frontend": False, "has_docker": False, "has_env_example": False})

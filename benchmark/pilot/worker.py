import contextlib
import json
import sys
import tempfile
from pathlib import Path

request = json.load(sys.stdin)
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder) / "fixture"
    root.mkdir()
    for name, content in request["files"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    sys.path.insert(0, "/workspace")
    with contextlib.redirect_stdout(sys.stderr):
        from src.analyze_repo import analyze
        profile = analyze(str(root))
    print(json.dumps(profile))

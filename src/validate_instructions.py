import argparse
import json
import re
import shlex
from pathlib import Path

if __package__:
    from .analyze_repo import analyze, read_repo_file, repo_files, safe_path
else:
    from analyze_repo import analyze, read_repo_file, repo_files, safe_path


def validate_instructions(text: str, repo_root: Path, profile: dict | None = None):
    repo_root = Path(repo_root).resolve()
    profile = profile or {}
    evidence = profile.get("evidence", {})
    command_evidence = evidence.get("commands", []) if isinstance(evidence, dict) else []
    framework_evidence = evidence.get("frameworks", []) if isinstance(evidence, dict) else []
    findings = []
    operations = {}
    heading = ""
    verified = False
    fenced = False

    def add(rule, severity, explanation, line, instruction, sources=None):
        findings.append({"rule": rule, "severity": severity, "explanation": explanation,
                         "instruction": instruction, "line": line, "evidence": sources or []})

    for number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if line.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or not line or line.startswith(">"):
            continue
        if line.startswith("#"):
            heading = line.lstrip("# ").lower()
            verified = bool(re.match(r"verified\b", heading))
            continue
        if re.fullmatch(r"verified (?:configuration|commands?)\s*:", line, re.IGNORECASE):
            verified = True
            continue
        if re.fullmatch(r"(?:documented|unverified|inferred)[^`]*:", line, re.IGNORECASE):
            verified = False
            continue
        if "example" in heading or re.search(r"\b(?:example|illustration|for instance|e\.g\.)\b", line, re.IGNORECASE):
            continue

        # --- paths explicitly identified for inspection or modification ---
        if re.search(r"\b(?:inspect|read|open|edit|modify|file|directory|path)\s+`", line, re.IGNORECASE) and not re.search(r"\b(?:create|example|may not exist)\b", line, re.IGNORECASE):
            for path in re.findall(r"`([^`]+)`", line):
                named_path = re.search(r"\b(?:file|directory|path)\s+`" + re.escape(path) + r"`", line, re.IGNORECASE)
                if not re.fullmatch(r"(?:\.?[\w.-]+/)*[\w.-]+/?", path) or not ("/" in path or "." in path or named_path):
                    continue
                target = repo_root / path
                if not safe_path(repo_root, target):
                    add("path_outside", "warning", "The referenced path is outside the repository or cannot be resolved safely.", number, original)
                elif not target.exists():
                    add("path_missing", "error", "The referenced repository path does not exist.", number, original)

        # --- narrow framework claims ---
        claim = re.search(r"\b(?:uses|built with|requires)\s+(fastapi|sqlmodel|react|vite)\b", line, re.IGNORECASE)
        if claim and not re.search(r"\b(?:may|might|could|not|never|avoid)\b", line, re.IGNORECASE):
            framework = claim.group(1).lower()
            sources = [item for item in framework_evidence if item.get("value") == framework]
            if framework in ("react", "vite") or not any(item.get("classification") == "verified" for item in sources):
                packages = []
                declared = False
                if framework in ("react", "vite"):
                    for path in repo_files(repo_root):
                        if path.name != "package.json":
                            continue
                        contents = read_repo_file(repo_root, path)
                        try:
                            data = json.loads(contents) if contents is not None else None
                        except ValueError:
                            continue
                        if isinstance(data, dict) and all(isinstance(data.get(section, {}), dict) for section in ("dependencies", "devDependencies")):
                            packages.append({"source": path.relative_to(repo_root).as_posix(), "key": "dependencies/devDependencies", "classification": "verified"})
                            for section in ("dependencies", "devDependencies"):
                                dependencies = data.get(section, {})
                                if isinstance(dependencies, dict) and framework in dependencies:
                                    declared = True
                if declared:
                    continue
                if packages:
                    add("framework_conflict", "warning", f"No detected package configuration declares {framework}; review the claim.", number, original, packages)
                else:
                    add("framework_unverified", "unverified", f"Available evidence does not verify the {framework} claim.", number, original, sources)

        # --- unconditional, directly opposing instructions ---
        operation = re.fullmatch(r"(?:[-*]\s*)?(always|never|do not)\s+((?:run|apply|execute)\s+[^.!?]+)[.!]?", line, re.IGNORECASE)
        if operation:
            action = operation.group(2).strip().lower()
            direction = "require" if operation.group(1).lower() == "always" else "forbid"
            previous = operations.get((action, "forbid" if direction == "require" else "require"))
            if previous:
                add("contradictory_instruction", "warning", f"This conflicts with the instruction on line {previous}.", number, original)
            operations[(action, direction)] = number

        # --- commands only in direct instructions or command lists ---
        if re.search(r"\b(?:do not|don't|never|avoid|without)\b", line, re.IGNORECASE):
            continue
        direct = re.match(r"^(?:[-*]\s*)?(?:verified\s*:\s*)?(?:always\s+)?(?:run|execute|invoke|use)\s+`([^`]+)`", line, re.IGNORECASE)
        listed = re.match(r"^[-*]\s+`([^`]+)`", line) if ("command" in heading or verified) else None
        bare = re.match(r"^(?:[-*]\s*)?(?:run|execute)\s+((?:cd\s+[^\s]+\s+&&\s+)?npm\s+run\s+\S+(?:\s+--prefix\s+\S+)?)", line, re.IGNORECASE)
        match = direct or listed or bare
        if not match:
            continue
        command = match.group(1).rstrip(".") if match is bare else match.group(1)
        if re.search(r"(?:\brm\s+-(?:[a-zA-Z]*r[a-zA-Z]*f|[a-zA-Z]*f[a-zA-Z]*r)\s+/(?:\s|$)|\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:sh|bash)\b|\b(?:git\s+commit|git\s+push)\b[^\n]*--no-verify\b)", command):
            add("unsafe_command", "warning", "The command matches a potentially unsafe pattern; review it before use.", number, original)

        directory = None
        location = re.search(r"working directory:\s*`([^`]+)`", line, re.IGNORECASE)
        if location:
            directory = location.group(1)
        else:
            location = re.search(r"\b(?:from|in)\s+`([^`]+)`", line, re.IGNORECASE)
            if location:
                directory = location.group(1)
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = []
        if len(parts) >= 5 and parts[0] == "cd" and parts[2] == "&&":
            directory = parts[1]
            parts = parts[3:]
        if len(parts) >= 3 and parts[:2] == ["npm", "run"]:
            script = parts[2]
            if "--prefix" in parts:
                index = parts.index("--prefix")
                if index + 1 < len(parts):
                    directory = parts[index + 1]
            script_sources = [item for item in command_evidence if item.get("type") == "package.json" and item.get("key") == f"scripts.{script}" and item.get("classification") == "verified"]
            if not script_sources:
                for path in repo_files(repo_root):
                    if path.name != "package.json":
                        continue
                    contents = read_repo_file(repo_root, path)
                    try:
                        data = json.loads(contents) if contents is not None else None
                    except ValueError:
                        continue
                    scripts = data.get("scripts", {}) if isinstance(data, dict) else None
                    if isinstance(scripts, dict) and isinstance(scripts.get(script), str):
                        script_sources.append({"source": path.relative_to(repo_root).as_posix(), "key": f"scripts.{script}", "classification": "verified", "working_directory": path.parent.relative_to(repo_root).as_posix()})
            if directory is None:
                add("working_directory", "warning", "The npm command does not specify a working directory.", number, original, script_sources)
            else:
                package = repo_root / directory / "package.json"
                if Path(directory).is_absolute() or not safe_path(repo_root, package):
                    add("working_directory", "warning", "The npm working directory is outside the repository or cannot be resolved safely.", number, original)
                else:
                    contents = read_repo_file(repo_root, package)
                    try:
                        data = json.loads(contents) if contents is not None else None
                    except ValueError:
                        data = None
                    scripts = data.get("scripts", {}) if isinstance(data, dict) else None
                    source = [{"source": package.relative_to(repo_root).as_posix(), "key": "scripts", "classification": "verified"}] if isinstance(scripts, dict) else []
                    if not isinstance(scripts, dict):
                        if any(item.get("working_directory") != directory for item in script_sources):
                            add("working_directory", "warning", "The script is recorded in a different working directory; this package cannot be verified.", number, original, script_sources)
                        else:
                            add("npm_unverified", "unverified", "The package scripts could not be verified in the specified directory.", number, original)
                    elif script not in scripts or not isinstance(scripts[script], str):
                        add("npm_script_missing", "error", "The specified package does not define this npm script.", number, original, source)
                        if any(item.get("working_directory") != directory for item in script_sources):
                            add("working_directory", "warning", "The script is recorded in a different working directory.", number, original, script_sources)

        else:
            locations = [item for item in command_evidence if item.get("value") == command and item.get("working_directory") is not None]
            if locations and directory is None:
                add("working_directory", "warning", "The command has recorded working-directory information that is missing from the instruction.", number, original, locations)
            elif locations and all(item.get("working_directory") != directory for item in locations):
                add("working_directory", "warning", "The stated working directory differs from the recorded command locations.", number, original, locations)

        if verified or (re.search(r"\bverified\b", line, re.IGNORECASE) and not re.search(r"\bnot\s+verified\b", line, re.IGNORECASE)):
            normalized = shlex.join(parts) if len(parts) >= 3 and parts[:2] == ["npm", "run"] else command
            candidates = [item for item in command_evidence if item.get("value") == normalized]
            matches = [item for item in candidates if directory is None or item.get("working_directory") == directory]
            if not any(item.get("classification") == "verified" for item in matches):
                add("command_unverified", "unverified", "The command is labeled verified, but the profile does not verify this definition and working directory.", number, original, candidates)
    return sorted(findings, key=lambda item: (item["line"], item["rule"], item["explanation"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instructions", type=Path)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text()) if args.profile else analyze(str(args.repo))
    findings = validate_instructions(args.instructions.read_text(), args.repo, profile)
    print(json.dumps(findings, indent=2))


if __name__ == "__main__":
    main()

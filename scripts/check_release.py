from __future__ import annotations

import argparse
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ENV_FILES = {".env.example"}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".gguf",
    ".log",
    ".pyc",
    ".safetensors",
    ".sqlite",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".sqlite-shm",
    ".sqlite-wal",
}
FORBIDDEN_PARTS = {
    ".crawl4ai",
    ".runtime",
    "__pycache__",
    "browser-profile",
    "browser-profiles",
    "browser-storage",
    "captured-pages",
    "model-cache",
}
LEGACY_PACKAGE_MARKERS = {"local" + "-web-rag", "local" + "_web_rag"}
REQUIRED = {
    ".env.example",
    ".github/workflows/ci.yml",
    "AGENTS.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/RELEASE_CHECKLIST.md",
    "sbom.cdx.json",
}


def _run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout


def tracked_files() -> set[str]:
    return {line for line in _run_git("ls-files").splitlines() if line}


def history_paths() -> set[str]:
    paths: set[str] = set()
    for line in _run_git("rev-list", "--objects", "--all").splitlines():
        _, separator, path = line.partition(" ")
        if separator and path:
            paths.add(path)
    return paths


def unsafe_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    parts = PurePosixPath(normalized).parts
    name = parts[-1] if parts else ""
    if name.startswith(".env") and name not in ALLOWED_ENV_FILES:
        return True
    if any(part in FORBIDDEN_PARTS for part in parts):
        return True
    return any(normalized.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)


def _archive_members(path: Path) -> list[str]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            return archive.getnames()
    raise SystemExit(f"Release check failed: unsupported artifact format: {path}")


def inspect_artifacts(directory: Path) -> list[str]:
    if not directory.is_dir():
        return [f"artifact directory does not exist: {directory}"]
    files = sorted(path for path in directory.iterdir() if path.is_file())
    artifacts = [path for path in files if path.name.endswith((".whl", ".tar.gz", ".zip"))]
    if not artifacts:
        return [f"artifact directory is empty: {directory}"]
    problems: list[str] = []
    problems.extend(
        f"unexpected artifact file: {path.name}"
        for path in files
        if path not in artifacts and not path.name.startswith(".")
    )
    for artifact in artifacts:
        for member in _archive_members(artifact):
            lowered = member.lower()
            if unsafe_path(member) or any(marker in lowered for marker in LEGACY_PACKAGE_MARKERS):
                problems.append(f"{artifact.name}: {member}")
    return problems


def _render_failure(label: str, paths: list[str]) -> None:
    rendered = "\n".join(f"  - {path}" for path in paths)
    raise SystemExit(f"Release check failed: {label}:\n{rendered}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check release tree, history, and archives")
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="skip the Git-history gate (for work before an approved history rewrite)",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        help="inspect all wheel/sdist archives in this directory",
    )
    args = parser.parse_args()

    tracked = tracked_files()
    unsafe = sorted(path for path in tracked if unsafe_path(path))
    if unsafe:
        _render_failure("runtime/private files are tracked", unsafe)

    if not args.current_only:
        unsafe_history = sorted(path for path in history_paths() if unsafe_path(path))
        if unsafe_history:
            _render_failure(
                "runtime/private paths remain in Git history; rotate affected credentials and "
                "rewrite every ref before publication",
                unsafe_history,
            )

    missing = sorted(path for path in REQUIRED if not (ROOT / path).is_file())
    if missing:
        _render_failure("required publication files are missing", missing)

    if args.artifacts:
        artifact_problems = inspect_artifacts(args.artifacts.resolve())
        if artifact_problems:
            _render_failure("unsafe or obsolete artifact members found", artifact_problems)

    print("Release tree, history, and artifact hygiene checks passed")


if __name__ == "__main__":
    main()

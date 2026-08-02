from __future__ import annotations

import compileall
import importlib
import pathlib
import tomllib

root = pathlib.Path(__file__).resolve().parents[1]
assert compileall.compile_dir(root / "src", quiet=1)
with (root / "pyproject.toml").open("rb") as handle:
    pyproject = tomllib.load(handle)
assert pyproject["project"]["name"] == "ai-websearch"
assert pyproject["project"]["scripts"] == {"ai-websearch": "ai_websearch.cli:main"}
package = importlib.import_module("ai_websearch")
assert package.__version__ == pyproject["project"]["version"]
scan_paths = list((root / "src").rglob("*.py")) + [root / ".env.example"]
scanned = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in scan_paths)
for forbidden in (
    "LLAMA_CPP_EMBEDDINGS_URL",
    "LLAMA_CPP_EMBEDDINGS_MODEL",
    "/v1/embeddings",
    "EMBEDDING_BACKEND=",
):
    assert forbidden not in scanned, forbidden

for forbidden in (
    "MODEL_CONTEXT_TOKENS",
    "LLAMA_CPP_DISCOVERY_PORTS",
    "CONTEXT_PROFILE",
    "LLAMA_CPP_TOKENIZE_URL",
):
    assert forbidden not in scanned, forbidden
assert not (root / "src/ai_websearch/profiles.py").exists()
assert not (root / "src/ai_websearch/token_budget.py").exists()
assert (root / "src/ai_websearch/llama_discovery.py").exists()
assert (root / "src/ai_websearch/context_budget.py").exists()
for removed in (
    root / "src/ai_websearch/source_scoring.py",
    root / "config/source_scoring.yml",
):
    assert not removed.exists()
assert "source_score" not in "\n".join(
    path.read_text(encoding="utf-8", errors="ignore")
    for path in (root / "src/ai_websearch").glob("*.py")
    if path.name != "store.py"
)

print("Package validation passed")

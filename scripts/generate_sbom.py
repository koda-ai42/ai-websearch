from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sbom.cdx.json"


def generate() -> str:
    with tempfile.TemporaryDirectory(prefix="ai-websearch-sbom-") as temporary:
        raw_output = Path(temporary) / "raw.cdx.json"
        subprocess.run(
            [
                "uv",
                "export",
                "--preview-features",
                "sbom-export",
                "--format",
                "cyclonedx1.5",
                "--no-dev",
                "--frozen",
                "--output-file",
                str(raw_output),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=60,
        )
        payload = json.loads(raw_output.read_text(encoding="utf-8"))
    payload.pop("serialNumber", None)
    payload.get("metadata", {}).pop("timestamp", None)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the deterministic locked SBOM")
    parser.add_argument("--write", action="store_true", help="replace the checked-in SBOM")
    args = parser.parse_args()
    rendered = generate()
    if args.write:
        OUTPUT.write_text(rendered, encoding="utf-8")
        print(f"Wrote {OUTPUT.relative_to(ROOT)}")
        return
    if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
        raise SystemExit("SBOM is stale; run `uv run python scripts/generate_sbom.py --write`")
    print("SBOM matches the locked production dependency graph")


if __name__ == "__main__":
    main()

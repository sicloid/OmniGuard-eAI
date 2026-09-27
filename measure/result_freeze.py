"""Create and verify an immutable G13 result-file inventory."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

SCHEMA = "omniguard.result-freeze/1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _files(root: Path, inputs: list[Path]) -> list[Path]:
    selected = set()
    for supplied in inputs:
        lexical = supplied if supplied.is_absolute() else root / supplied
        if lexical.is_symlink():
            raise ValueError(f"symlink evidence is forbidden: {supplied}")
        path = lexical.resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError(f"input escapes repository root: {supplied}")
        candidates = [path] if path.is_file() else sorted(path.rglob("*"))
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError(f"symlink evidence is forbidden: {candidate}")
            if candidate.is_file():
                selected.add(candidate)
    if not selected:
        raise ValueError("freeze requires at least one evidence file")
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix())


def create(
    root: Path,
    inputs: list[Path],
    declaration: Path,
    output: Path,
    *,
    frozen_at_utc: str,
) -> dict:
    root = Path(root).resolve(strict=True)
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"freeze manifest already exists: {output}")
    if not frozen_at_utc.endswith("Z") or "T" not in frozen_at_utc:
        raise ValueError("frozen_at_utc must be an explicit UTC timestamp ending in Z")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError("repository must be clean before freezing results")
    declaration_path = (declaration if declaration.is_absolute() else root / declaration).resolve(
        strict=True
    )
    if not declaration_path.is_relative_to(root) or not declaration_path.is_file():
        raise ValueError("declaration must be a repository file")
    declaration_doc = json.loads(declaration_path.read_text(encoding="utf-8"))
    files = _files(root, inputs)
    resolved_output = output.resolve()
    if resolved_output in files:
        raise ValueError("output cannot be one of the frozen inputs")
    document = {
        "schema": SCHEMA,
        "frozen_at_utc": frozen_at_utc,
        "git_commit": _git(root, "rev-parse", "HEAD"),
        "declaration": {
            "path": declaration_path.relative_to(root).as_posix(),
            "sha256": _sha256(declaration_path),
            "content": declaration_doc,
        },
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    output.with_suffix(output.suffix + ".sha256").write_text(f"{_sha256(output)}  {output.name}\n")
    return document


def verify(root: Path, manifest: Path) -> dict:
    root, manifest = Path(root).resolve(strict=True), Path(manifest).resolve(strict=True)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA:
        raise ValueError("unexpected result-freeze schema")
    declaration = document["declaration"]
    declaration_path = root / declaration["path"]
    if _sha256(declaration_path) != declaration["sha256"]:
        raise ValueError("freeze declaration drift")
    for row in document["files"]:
        lexical = root / row["path"]
        if lexical.is_symlink():
            raise ValueError(f"unsafe frozen path: {row['path']}")
        path = lexical.resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError(f"unsafe frozen path: {row['path']}")
        if path.stat().st_size != row["bytes"] or _sha256(path) != row["sha256"]:
            raise ValueError(f"frozen evidence drift: {row['path']}")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("create")
    freeze.add_argument("--root", type=Path, default=Path.cwd())
    freeze.add_argument("--input", action="append", type=Path, required=True)
    freeze.add_argument("--declaration", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--frozen-at-utc", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--root", type=Path, default=Path.cwd())
    check.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.command == "create":
        result = create(
            args.root,
            args.input,
            args.declaration,
            args.output,
            frozen_at_utc=args.frozen_at_utc,
        )
        print(json.dumps({"git_commit": result["git_commit"], "files": len(result["files"])}))
    else:
        result = verify(args.root, args.manifest)
        print(json.dumps({"git_commit": result["git_commit"], "files": len(result["files"])}))


if __name__ == "__main__":
    main()

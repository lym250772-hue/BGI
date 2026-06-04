#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Package local inference models into small transferable chunks.

The script intentionally excludes training checkpoints and optimizer states.
It creates split files under model_release/ so they can be sent through tools
that reject one large upload.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = PROJECT_ROOT / "data" / "models"
OUTPUT_ROOT = PROJECT_ROOT / "model_release"

ROBERTA_FILES = [
    "config.json",
    "label_map.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "training_metrics.json",
    "vocab.txt",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_roberta(output: Path) -> None:
    src = MODEL_ROOT / "roberta_classifier"
    if not src.exists():
        raise FileNotFoundError(f"Missing model directory: {src}")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ROBERTA_FILES:
            path = src / name
            if path.exists():
                zf.write(path, arcname=f"data/models/roberta_classifier/{name}")


def zip_embedding(output: Path) -> None:
    src = MODEL_ROOT / "paraphrase-multilingual-MiniLM-L12-v2"
    if not src.exists():
        raise FileNotFoundError(f"Missing embedding model directory: {src}")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if path.is_file():
                arcname = path.relative_to(PROJECT_ROOT)
                zf.write(path, arcname=str(arcname).replace("\\", "/"))


def split_file(path: Path, chunk_mb: int) -> list[Path]:
    chunk_size = chunk_mb * 1024 * 1024
    parts: list[Path] = []
    with path.open("rb") as src:
        index = 1
        while True:
            data = src.read(chunk_size)
            if not data:
                break
            part = path.with_name(f"{path.name}.part{index:03d}")
            part.write_bytes(data)
            parts.append(part)
            index += 1
    return parts


def write_restore_script(output_dir: Path) -> None:
    script = output_dir / "restore_model_parts.py"
    script.write_text(
        '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restore BGI model zip files from .partNNN chunks."""
from __future__ import annotations

from pathlib import Path


def restore(prefix: str) -> None:
    parts = sorted(Path(".").glob(f"{prefix}.part*"))
    if not parts:
        print(f"[skip] no parts found for {prefix}")
        return
    out = Path(prefix)
    with out.open("wb") as dst:
        for part in parts:
            print(f"append {part}")
            dst.write(part.read_bytes())
    print(f"restored {out}")


restore("roberta_classifier.zip")
restore("embedding_minilm.zip")
print("Now unzip both zip files into the BGI project root.")
''',
        encoding="utf-8",
    )


def write_readme(output_dir: Path, package_info: list[dict]) -> None:
    lines = [
        "# BGI model transfer package",
        "",
        "Send all .partNNN files and restore_model_parts.py to your teammate.",
        "",
        "Restore on teammate machine:",
        "",
        "```bash",
        "python restore_model_parts.py",
        "python -m zipfile -e roberta_classifier.zip .",
        "python -m zipfile -e embedding_minilm.zip .",
        "```",
        "",
        "Expected final paths:",
        "",
        "```text",
        "data/models/roberta_classifier",
        "data/models/paraphrase-multilingual-MiniLM-L12-v2",
        "```",
        "",
        "Packages:",
        "",
    ]
    for item in package_info:
        lines.append(
            f"- {item['name']}: {item['size_mb']:.2f} MB, "
            f"{item['parts']} parts, sha256={item['sha256']}"
        )
    (output_dir / "README_FOR_TEAMMATE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Package BGI local models into split archives")
    parser.add_argument("--chunk-mb", type=int, default=90, help="Split size in MB")
    parser.add_argument("--clean", action="store_true", help="Remove old model_release first")
    parser.add_argument("--skip-embedding", action="store_true", help="Only package roberta classifier")
    args = parser.parse_args()

    if args.clean and OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    packages: list[tuple[str, Path]] = []
    roberta_zip = OUTPUT_ROOT / "roberta_classifier.zip"
    zip_roberta(roberta_zip)
    packages.append(("roberta_classifier.zip", roberta_zip))

    if not args.skip_embedding:
        embedding_zip = OUTPUT_ROOT / "embedding_minilm.zip"
        zip_embedding(embedding_zip)
        packages.append(("embedding_minilm.zip", embedding_zip))

    info: list[dict] = []
    for name, path in packages:
        package_hash = sha256_file(path)
        parts = split_file(path, chunk_mb=args.chunk_mb)
        info.append(
            {
                "name": name,
                "size_mb": path.stat().st_size / 1024 / 1024,
                "parts": len(parts),
                "sha256": package_hash,
            }
        )
        path.unlink()

    write_restore_script(OUTPUT_ROOT)
    write_readme(OUTPUT_ROOT, info)

    print(f"Model packages written to: {OUTPUT_ROOT}")
    for item in info:
        print(
            f"{item['name']}: {item['size_mb']:.2f} MB, "
            f"{item['parts']} parts, sha256={item['sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Index a GitHub repo (or local folder) into <data_home>/repos/<name>/.

Usage:
    python vectorize.py <github_url_or_local_path> [--name NAME] [--max-file-mb FLOAT]

Output dir is always the plugin's repos dir; this is intentional — there is no
project-local index option. Everything goes through the canonical location so
queries from any working directory find the index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from chunker import Chunk, chunk_file, detect_language  # noqa: E402
from db import (  # noqa: E402
    EMBEDDING_DIM,
    init_schema,
    insert_chunks,
    open_db,
    reset_index,
    set_meta,
)
from embedder import Embedder  # noqa: E402
from paths import repos_dir  # noqa: E402


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "bower_components",
    "venv", ".venv", "env", "python-env",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "dist", "build", "out", "target", "bin", "obj",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
    "coverage", ".coverage", "htmlcov",
    ".idea", ".vscode", ".vs",
    ".cache", ".gradle", ".m2",
    "vendor", "Pods", "DerivedData",
    "site-packages",
}

SKIP_EXTS = {
    ".pyc", ".pyo", ".so", ".o", ".obj", ".dll", ".exe", ".bin", ".class", ".jar", ".war",
    ".a", ".dylib", ".lib",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".tiff", ".webp", ".svg",
    ".mp3", ".mp4", ".avi", ".mov", ".webm", ".wav", ".ogg", ".flac",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".lock",
    ".db", ".sqlite", ".sqlite3", ".onnx", ".pkl", ".npz", ".parquet",
    ".min.js", ".min.css",
    ".map",
}

SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Pipfile.lock",
    "poetry.lock", "Cargo.lock", "Gemfile.lock", "composer.lock",
    ".DS_Store", "Thumbs.db",
}

DEFAULT_MAX_BYTES = int(1.5 * 1024 * 1024)


def should_skip(rel_path: str, size_bytes: int, max_bytes: int) -> Optional[str]:
    name = os.path.basename(rel_path)
    if name in SKIP_FILENAMES:
        return "skip-filename"
    lower = name.lower()
    for ext in SKIP_EXTS:
        if lower.endswith(ext):
            return f"skip-ext:{ext}"
    if size_bytes > max_bytes:
        return f"too-large:{size_bytes}"
    return None


def walk_repo(root: Path, max_bytes: int) -> List[Path]:
    keep: List[Path] = []
    skipped = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        # Re-add .github explicitly (CI configs may be useful).
        for d in list(os.listdir(dirpath)):
            full = os.path.join(dirpath, d)
            if d == ".github" and os.path.isdir(full) and d not in dirnames:
                dirnames.append(d)
        for fname in filenames:
            full = Path(dirpath) / fname
            try:
                size = full.stat().st_size
            except OSError:
                continue
            rel = str(full.relative_to(root))
            if should_skip(rel, size, max_bytes):
                skipped += 1
                continue
            keep.append(full)
    print(f"[walk] candidate files: {len(keep)}  skipped: {skipped}", flush=True)
    return keep


# ---------------------------------------------------------------------------
# Repo acquisition
# ---------------------------------------------------------------------------

_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?/?$"
)


def is_github_url(s: str) -> bool:
    return bool(_GITHUB_URL_RE.match(s.strip()))


def parse_github_url(url: str) -> tuple[str, str]:
    m = _GITHUB_URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"Not a GitHub URL: {url!r}")
    return m.group("owner"), m.group("repo")


def acquire_source(target: str, dest: Path) -> Path:
    source_dir = dest / "source"
    if source_dir.exists():
        print(f"[acquire] removing existing source dir: {source_dir}", flush=True)
        shutil.rmtree(source_dir)

    if is_github_url(target):
        print(f"[acquire] cloning {target}  ->  {source_dir}", flush=True)
        cmd = ["git", "clone", "--depth", "1", "--single-branch", target, str(source_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed:\n{result.stderr}")
    else:
        src = Path(target).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(f"Local path not found: {src}")
        if src.is_file():
            raise ValueError(f"Local path is a file, not a directory: {src}")
        print(f"[acquire] copying {src}  ->  {source_dir}", flush=True)
        shutil.copytree(src, source_dir, ignore=shutil.ignore_patterns(
            ".git", "node_modules", "__pycache__", ".venv", "venv", "python-env",
            "dist", "build", ".next", "target",
        ))
    return source_dir


def repo_name_from_target(target: str, override: Optional[str]) -> str:
    if override:
        return override
    if is_github_url(target):
        owner, repo = parse_github_url(target)
        return repo
    return Path(target).expanduser().resolve().name


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def read_text_file(path: Path) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def build_embedding_text(chunk: Chunk) -> str:
    header_bits: List[str] = [chunk.file_path]
    if chunk.name:
        header_bits.append(f"{chunk.kind} {chunk.name}".strip())
    header = " :: ".join(header_bits)
    return f"{header}\n\n{chunk.content}"


def index_repo(target: str, repo_name_override: Optional[str], max_bytes: int) -> dict:
    t_start = time.perf_counter()
    repo_name = repo_name_from_target(target, repo_name_override)
    output_dir = repos_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / repo_name
    dest.mkdir(parents=True, exist_ok=True)

    source_dir = acquire_source(target, dest)
    files = walk_repo(source_dir, max_bytes)

    print("[chunk] chunking files...", flush=True)
    all_rows: List[dict] = []
    all_texts: List[str] = []
    per_file_counts: Dict[str, int] = {}
    files_indexed = 0

    for f in files:
        text = read_text_file(f)
        if text is None:
            continue
        rel = str(f.relative_to(source_dir)).replace("\\", "/")
        chunks = chunk_file(rel, text)
        if not chunks:
            continue
        files_indexed += 1
        per_file_counts[rel] = len(chunks)
        for c in chunks:
            row = c.to_row()
            row["content_hash"] = hashlib.sha1(c.content.encode("utf-8", errors="ignore")).hexdigest()
            all_rows.append(row)
            all_texts.append(build_embedding_text(c))

    print(f"[chunk] {files_indexed} files -> {len(all_rows)} chunks", flush=True)
    if not all_rows:
        raise RuntimeError("No chunks were produced. Is the repo empty?")

    print("[embed] starting embeddings...", flush=True)
    embedder = Embedder()
    if embedder.dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding dim mismatch: model returned {embedder.dim}, schema expects {EMBEDDING_DIM}."
        )

    BATCH = 64
    embeddings: List[List[float]] = []
    n = len(all_texts)
    for start in range(0, n, BATCH):
        batch = all_texts[start: start + BATCH]
        embeddings.extend(embedder.embed_batch(batch, batch_size=BATCH))
        print(f"[embed] {min(start + BATCH, n)}/{n}", flush=True)

    db_path = dest / "index.sqlite"
    if db_path.exists():
        db_path.unlink()
    print(f"[db] writing index to {db_path}", flush=True)
    conn = open_db(str(db_path))
    init_schema(conn, embedding_dim=embedder.dim)
    reset_index(conn)
    set_meta(conn, "repo_name", repo_name)
    set_meta(conn, "source_target", target)
    set_meta(conn, "embedding_model", embedder.model_name)
    set_meta(conn, "embedding_dim", str(embedder.dim))
    set_meta(conn, "indexed_at", str(int(time.time())))

    DB_BATCH = 500
    for start in range(0, len(all_rows), DB_BATCH):
        insert_chunks(conn, all_rows[start: start + DB_BATCH], embeddings[start: start + DB_BATCH])
    conn.close()

    elapsed = round(time.perf_counter() - t_start, 2)

    manifest = {
        "repo_name": repo_name,
        "source_target": target,
        "source_dir": str(source_dir),
        "db_path": str(db_path),
        "embedding_model": embedder.model_name,
        "embedding_dim": embedder.dim,
        "files_indexed": files_indexed,
        "chunks_indexed": len(all_rows),
        "elapsed_seconds": elapsed,
        "files": sorted(
            [{"path": p, "chunks": c} for p, c in per_file_counts.items()],
            key=lambda r: -r["chunks"],
        ),
    }
    manifest_path = dest / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {
        "repo_name": repo_name,
        "source_dir": str(source_dir),
        "db_path": str(db_path),
        "manifest_path": str(manifest_path),
        "files_indexed": files_indexed,
        "chunks_indexed": len(all_rows),
        "elapsed_seconds": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Index a GitHub repo or local folder.")
    parser.add_argument("target", help="GitHub URL or local directory path")
    parser.add_argument("--name", default=None,
                        help="Override the indexed repo's directory name")
    parser.add_argument("--max-file-mb", type=float, default=1.5,
                        help="Skip files larger than this many megabytes (default: 1.5)")
    args = parser.parse_args()

    max_bytes = int(args.max_file_mb * 1024 * 1024)

    try:
        summary = index_repo(args.target, args.name, max_bytes)
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

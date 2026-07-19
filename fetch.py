#!/usr/bin/env python3
"""Fetch Nordic Semiconductor SVD files from the nrfx repo and organize them.

Incremental and re-runnable. Python 3 stdlib only (git must be on PATH).

Every run starts with a cheap metadata check: 'git ls-remote <url> HEAD'
(no artifact download). If the remote sha equals the one recorded in
manifest.json and every file the manifest lists for this source exists on
disk, the script prints 'up to date' and exits 0 without touching anything.

Only when the sha changed, or manifest.json / SVD files are missing, does it:
  1. shallow-clone https://github.com/NordicSemiconductor/nrfx into .work/nrfx
  2. find *.svd under bsp/stable/mdk/ (fallback: glob the whole clone)
  3. validate each file with xml.etree (well-formed, root element 'device')
  4. replace this source's files under <Family>/<Device>.svd at the repo root
  5. refresh the nrfx LICENSE copy in LICENSES/nrfx-LICENSE.txt
  6. rewrite manifest.json (sha, files, stats, generated = current date)
  7. delete .work

Every artifact download is logged with a 'DOWNLOAD artifact:' line; a no-op
run performs zero artifact downloads. Exit code is 0 both when up to date
and when updated; nonzero only on real errors.
"""

import datetime
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".work"
SVD_BASE = ROOT
LIC_DIR = ROOT / "LICENSES"
MANIFEST = ROOT / "manifest.json"

# Never delete these when cleaning family directories on a full rebuild.
PROTECTED = {
    ".git", ".github", ".gitignore", ".work",
    "LICENSES", "README.md", "manifest.json", "fetch.py",
}

NRFX_URL = "https://github.com/NordicSemiconductor/nrfx"
SOURCE_NAME = "nrfx"

ARTIFACT_DOWNLOADS = 0

# filename prefix -> family, longest prefix wins
FAMILY_PREFIXES = [
    ("nrf54l", "nRF54L"),
    ("nrf54h", "nRF54H"),
    ("nrf51", "nRF51"),
    ("nrf52", "nRF52"),
    ("nrf53", "nRF53"),
    ("nrf71", "nRF71"),
    ("nrf91", "nRF91"),
    ("nrf92", "nRF92"),
]


def family_for(stem: str) -> str:
    low = stem.lower()
    for prefix, fam in FAMILY_PREFIXES:
        if low.startswith(prefix):
            return fam
    # fallback: nrf<digits><optional letter> -> nRF<digits><LETTER>
    m = re.match(r"nrf(\d+)([a-z]?)", low)
    if m:
        return "nRF" + m.group(1) + m.group(2).upper()
    return "Other"


def run(cmd, **kw):
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def clean_family_dirs():
    """Full-rebuild cleanup: remove only family dirs, never protected entries.

    SVD_BASE is the repo root, so this must never touch .git, .github,
    LICENSES, the script itself or the manifest. It deletes every top-level
    directory whose name is not in PROTECTED (the family folders).
    """
    for child in SVD_BASE.iterdir():
        if child.is_dir() and child.name not in PROTECTED:
            shutil.rmtree(child, onerror=_rm_force)


def log_artifact_download(desc: str) -> None:
    global ARTIFACT_DOWNLOADS
    ARTIFACT_DOWNLOADS += 1
    print(f"DOWNLOAD artifact: {desc}")


def remote_head_sha(url: str) -> str:
    """Cheap metadata check: ask the remote for its HEAD sha, no download."""
    print(f"metadata check: git ls-remote {url} HEAD")
    out = subprocess.run(
        ["git", "ls-remote", url, "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "HEAD":
            return parts[0]
    raise RuntimeError(f"cannot parse 'git ls-remote {url} HEAD' output: {out!r}")


def load_manifest():
    if not MANIFEST.is_file():
        return None
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARNING: unreadable manifest.json ({e}), forcing full fetch",
              file=sys.stderr)
        return None


def recorded_sha(manifest):
    if not manifest:
        return None
    for src in manifest.get("sources", []):
        if src.get("name") == SOURCE_NAME:
            return src.get("version")
    return None


def local_files_complete(manifest) -> bool:
    """True when every file the manifest lists for this source exists."""
    if not manifest:
        return False
    entries = [e for e in manifest.get("files", [])
               if e.get("source") == SOURCE_NAME]
    if not entries:
        return False
    for e in entries:
        if not (ROOT / e["path"]).is_file():
            print(f"missing local file: {e['path']}")
            return False
    return True


def fetch_nrfx(old_manifest) -> int:
    """Download the nrfx source and rebuild its files, manifest and license."""
    if WORK.exists():
        shutil.rmtree(WORK, onerror=_rm_force)
    WORK.mkdir(parents=True)

    clone = WORK / "nrfx"
    log_artifact_download(f"git clone --depth 1 {NRFX_URL}")
    run(["git", "clone", "--depth", "1", NRFX_URL, str(clone)])
    sha = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    print("nrfx HEAD:", sha)

    mdk = clone / "bsp" / "stable" / "mdk"
    if mdk.is_dir():
        svds = sorted(mdk.rglob("*.svd"))
        location = "bsp/stable/mdk"
    else:
        svds = sorted(clone.rglob("*.svd"))
        location = "repo-wide glob (bsp/stable/mdk absent)"
    print(f"found {len(svds)} .svd files under {location}")
    if not svds:
        print("ERROR: no SVD files found", file=sys.stderr)
        return 1

    # validate, then copy
    valid, invalid = [], []
    for p in svds:
        try:
            root = ET.parse(p).getroot()
            tag = root.tag.split("}")[-1]  # strip namespace if any
            if tag != "device":
                invalid.append((p, f"root element is '{tag}', not 'device'"))
            else:
                valid.append(p)
        except ET.ParseError as e:
            invalid.append((p, f"XML parse error: {e}"))
    for p, why in invalid:
        print(f"SKIP {p.name}: {why}", file=sys.stderr)

    # remove only this source's previous files, keep any other source's files
    if old_manifest:
        for e in old_manifest.get("files", []):
            if e.get("source") == SOURCE_NAME:
                old = ROOT / e["path"]
                if old.is_file():
                    old.unlink()
    else:
        clean_family_dirs()

    new_entries = []
    for p in valid:
        fam = family_for(p.stem)
        dest = SVD_BASE / fam / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        new_entries.append({
            "path": f"{fam}/{p.name}",
            "device": p.stem,
            "family": fam,
            "source": SOURCE_NAME,
            "provenance": "pristine",
        })

    # drop family dirs left empty after the replacement
    for d in sorted(SVD_BASE.iterdir()):
        if d.is_dir() and d.name not in PROTECTED and not any(d.iterdir()):
            d.rmdir()

    # license
    LIC_DIR.mkdir(exist_ok=True)
    lic_src = None
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING"):
        cand = clone / name
        if cand.is_file():
            lic_src = cand
            break
    if lic_src:
        shutil.copy2(lic_src, LIC_DIR / "nrfx-LICENSE.txt")
        print("copied license:", lic_src.name)
    else:
        print("WARNING: no LICENSE file found in nrfx clone", file=sys.stderr)

    # manifest: replace this source's entries, keep everything else
    files_entries = [e for e in (old_manifest or {}).get("files", [])
                     if e.get("source") != SOURCE_NAME]
    files_entries += new_entries
    files_entries.sort(key=lambda e: e["path"].lower())
    total_bytes = sum((ROOT / e["path"]).stat().st_size for e in files_entries)

    sources = [s for s in (old_manifest or {}).get("sources", [])
               if s.get("name") != SOURCE_NAME]
    sources.append({
        "name": SOURCE_NAME,
        "url": NRFX_URL,
        "version": sha,
        "license": "BSD-3-Clause",
        "files": len(new_entries),
    })

    manifest = {
        "vendor": "Nordic Semiconductor",
        "generated": datetime.date.today().isoformat(),
        "sources": sources,
        "files": files_entries,
        "stats": {
            "total_files": len(files_entries),
            "total_bytes": total_bytes,
        },
    }
    if invalid:
        manifest["invalid_files_removed"] = [
            {"file": p.name, "reason": why} for p, why in invalid
        ]
    MANIFEST.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    shutil.rmtree(WORK, onerror=_rm_force)
    print(f"done: {len(files_entries)} files, {total_bytes} bytes "
          f"({total_bytes / 1024 / 1024:.1f} MiB), {len(invalid)} rejected")
    return 0


def main() -> int:
    remote_sha = remote_head_sha(NRFX_URL)
    manifest = load_manifest()
    local_sha = recorded_sha(manifest)

    if local_sha == remote_sha and local_files_complete(manifest):
        print("up to date")
        print(f"artifact downloads: {ARTIFACT_DOWNLOADS}")
        return 0

    if local_sha != remote_sha:
        print(f"nrfx changed: {local_sha} -> {remote_sha}")
    else:
        print("local files incomplete, rebuilding nrfx source")
    rc = fetch_nrfx(manifest)
    print(f"artifact downloads: {ARTIFACT_DOWNLOADS}")
    return rc


def _rm_force(func, path, exc_info):
    # git makes objects read-only on Windows; clear the bit and retry
    import os
    import stat
    os.chmod(path, stat.S_IWRITE)
    func(path)


if __name__ == "__main__":
    sys.exit(main())

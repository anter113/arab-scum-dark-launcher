import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Build mod_manifest.json for the launcher")
    ap.add_argument("--dir", required=True, help="folder containing the .pak files")
    ap.add_argument("--repo", required=True, help="GitHub OWNER/REPO")
    ap.add_argument("--tag", default="mods", help="release tag holding the paks")
    ap.add_argument("--out", default="publish/mod_manifest.json")
    args = ap.parse_args()

    src = Path(args.dir)
    if not src.is_dir():
        raise SystemExit(f"not a folder: {src}")
    paks = sorted(p for p in src.iterdir()
                  if p.is_file() and p.suffix.lower() == ".pak" and ".prev-" not in p.name)
    if not paks:
        raise SystemExit(f"no .pak files in {src}")

    items = []
    for p in paks:
        size = p.stat().st_size
        print(f"hashing {p.name} ({size / 1048576:.1f} MB)")
        items.append({"path": p.name, "size": size, "sha": sha256_file(p)})

    manifest = {
        "schema": 1,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": f"https://github.com/{args.repo}/releases/download/{args.tag}",
        "items": items,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(items)} items, {sum(i['size'] for i in items) / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()

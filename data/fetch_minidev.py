"""Download and extract BIRD Mini-Dev into data/raw/ (nothing here is committed)."""
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip"
RAW = Path(__file__).resolve().parent / "raw"
ZIP = RAW / "minidev.zip"
OUT = RAW / "minidev"


def download() -> None:
    if ZIP.exists():
        print(f"already downloaded: {ZIP}")
        return
    RAW.mkdir(parents=True, exist_ok=True)
    tmp = ZIP.with_suffix(".part")
    print(f"downloading {URL} (~800 MB)")
    with urllib.request.urlopen(URL) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r{done * 100 // total:3d}%", end="", flush=True)
    print()
    tmp.rename(ZIP)


def extract() -> None:
    if OUT.exists():
        print(f"already extracted: {OUT}")
        return
    root = OUT.resolve()
    with zipfile.ZipFile(ZIP) as zf:
        for member in zf.infolist():
            name = member.filename
            if name.startswith("__MACOSX/") or name.endswith(".DS_Store"):
                continue
            dest = (OUT / name).resolve()
            if not dest.is_relative_to(root):
                sys.exit(f"refusing unsafe path in zip: {name}")
            if member.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
    print(f"extracted to {OUT}")


if __name__ == "__main__":
    download()
    extract()

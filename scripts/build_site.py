"""Build only the public, synthetic site; never read runtime ledgers or credentials."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build/site"


def build():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "landing.css", "sample.html", "sample.js", "sample.md", "sample-data.json"):
        shutil.copy2(ROOT / "site" / name, OUTPUT / name)
    static = ROOT / "agent/web/static"
    for name in ("briefing.js", "review.js", "app.js", "workspace.css", "favicon.svg"):
        shutil.copy2(static / name, OUTPUT / name)
    fonts = OUTPUT / "fonts"
    fonts.mkdir(exist_ok=True)
    for name in ("dm-sans-latin.woff2", "dm-mono-400-latin.woff2", "fraunces-600-latin.woff2", "OFL.txt"):
        shutil.copy2(static / "fonts" / name, fonts / name)


if __name__ == "__main__":
    build()

"""Build only the public, synthetic site; never read runtime ledgers or credentials."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build/site"


def build():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "site").iterdir():
        if source.is_file():
            shutil.copy2(source, OUTPUT / source.name)
    static = ROOT / "agent/web/static"
    shutil.copy2(static / "briefing.js", OUTPUT / "briefing.js")
    shutil.copy2(static / "favicon.svg", OUTPUT / "favicon.svg")
    html = (static / "index.html").read_text(encoding="utf-8")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    (OUTPUT / "sample.css").write_text(css, encoding="utf-8")


if __name__ == "__main__":
    build()

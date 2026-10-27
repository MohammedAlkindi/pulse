"""The browser review formats Markdown while keeping captured source HTML inert."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_formats_review_without_executing_source_html():
    node = shutil.which("node")
    if not node:
        pytest.skip("Browser renderer test requires Node.js")
    renderer = Path(__file__).parents[1] / "agent/web/static/briefing.js"
    text = "# Weekly Pulse\n## Commitments\n- **You promised:** <img src=x onerror=alert(1)> [1]\n\n| Source | Count |\n| --- | --- |\n| Gmail | 2 |\n\n## Sources\n1. `gmail:demo` — https://example.com/evidence\n\n[unsafe](javascript:alert(1))"
    script = renderer.read_text(encoding="utf-8") + "\nconsole.log(renderBriefing(" + json.dumps(text) + "));"
    html = subprocess.check_output([node, "-e", script], text=True, encoding="utf-8")
    assert "<h2>Weekly Pulse</h2>" in html and "<strong>You promised:</strong>" in html
    assert "<table>" in html and '<th scope="col">Source</th>' in html
    assert 'href="#brief-source-1"' in html and 'id="brief-source-1"' in html
    assert 'href="https://example.com/evidence"' in html
    assert "<img" not in html and "&lt;img" in html
    assert 'href="javascript:' not in html

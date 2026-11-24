"""Write summaries and a self-contained HTML report for a set of results."""
from __future__ import annotations

from pathlib import Path
from typing import List

from .summarise import load, summarise

VIEWER = Path(__file__).parent / 'viewer.html'
PLACEHOLDER = '<script id="data" type="application/x-ndjson"></script>'


def render_html(paths: List[Path]) -> str:
    """Return viewer.html with the given JSONL results embedded."""
    # "<\/" is a valid JSON escape and stops "</script>" ending the block early
    data = ''.join(Path(p).read_text() for p in paths).replace('</', '<\\/')
    return VIEWER.read_text().replace(
        PLACEHOLDER,
        f'<script id="data" type="application/x-ndjson">\n{data}</script>',
    )


def write_reports(out_dir: Path, paths: List[Path], stat: str = 'p50') -> str:
    """Write summary.txt, summary.md and report.html; return the text summary."""
    runs = load(paths)
    text = summarise(runs, stat)
    (out_dir / 'summary.txt').write_text(text)
    (out_dir / 'summary.md').write_text(summarise(runs, stat, markdown=True))
    (out_dir / 'report.html').write_text(render_html(paths))
    return text

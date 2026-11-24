#!/usr/bin/env python3
"""Write a self-contained HTML report: viewer.html with the given results embedded.

Usage: report.py RESULTS.jsonl [MORE.jsonl...] > report.html
"""
import sys
from pathlib import Path

PLACEHOLDER = '<script id="data" type="application/x-ndjson"></script>'

viewer = (Path(__file__).parent / 'viewer.html').read_text()
# "<\/" is a valid JSON escape and stops "</script>" ending the block early
data = ''.join(Path(path).read_text() for path in sys.argv[1:]).replace('</', '<\\/')
sys.stdout.write(viewer.replace(
    PLACEHOLDER,
    f'<script id="data" type="application/x-ndjson">\n{data}</script>',
))

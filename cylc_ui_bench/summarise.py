"""Summarise JSONL results as text or markdown tables.

Runs are grouped by suite and scale. For each scenario and label: the median,
min and max over runs of each run's median latency (or mean, with
stat='mean'), and the speed-up of each label relative to the first one.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable, List

STATS = ('p50', 'mean')


def load(paths: Iterable[Path]) -> List[dict]:
    """Read runs from JSONL files."""
    return [
        json.loads(line)
        for path in paths
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]


def group_key(run: dict) -> str:
    meta = run['meta']
    return json.dumps(
        [meta.get('suite', 'store'), meta.get('counts') or meta.get('scale')],
        sort_keys=True,
    )


def groups(runs: List[dict]) -> List[List[dict]]:
    """Split runs by suite and scale, smallest store workflows first."""
    grouped = defaultdict(list)
    for run in runs:
        grouped[group_key(run)].append(run)

    def size(group):
        counts = group[0]['meta'].get('counts') or {}
        return (counts.get('tasks', 0), counts.get('cycles', 0))

    return sorted(grouped.values(), key=size)


def summarise(runs: List[dict], stat: str = 'p50', markdown: bool = False) -> str:
    """Return a summary of all groups of runs."""
    if not runs:
        return 'no results\n'
    printer = _markdown if markdown else _text
    return ''.join(_group(group, stat, printer) for group in groups(runs))


def _group(runs, stat, printer):
    warnings = []
    for key in ('vue', 'vueBuild', 'gc', 'iterations'):
        values = {json.dumps(r['meta'].get(key), sort_keys=True) for r in runs}
        if len(values) > 1:
            warnings.append(f'WARNING: runs differ in {key}: {sorted(values)}')

    labels = list(dict.fromkeys(r['meta']['label'] for r in runs))
    scenarios = list(dict.fromkeys(res['name'] for r in runs for res in r['results']))
    values = defaultdict(list)
    for r in runs:
        for res in r['results']:
            if res['state'] == 'completed':
                values[res['name'], r['meta']['label']].append(res[stat])

    # rows of (scenario, [(median, min, max, n, speed-up) or None per label])
    rows = []
    for scenario in scenarios:
        cells = []
        for label in labels:
            xs = values.get((scenario, label))
            if not xs:
                cells.append(None)
                continue
            median = statistics.median(xs)
            base_median = cells[0][0] if cells and cells[0] else None
            speedup = base_median / median if base_median else None
            cells.append((median, min(xs), max(xs), len(xs), speedup))
        rows.append((scenario, cells))

    meta = runs[0]['meta']
    suite = meta.get('suite', 'store')
    counts = meta.get('counts')
    if counts:
        heading = (
            f"{suite}: {counts['tasks']} tasks, {counts['jobs']} jobs,"
            f" {counts['families']} families, {counts['cycles']} cycles"
        )
    else:
        heading = f"{suite}: {json.dumps(meta.get('scale'))}"
    details = (
        f"vue {meta.get('vue')} ({meta.get('vueBuild')}), node {meta.get('node')},"
        f" forced gc: {meta.get('gc', False)},"
        f" {meta.get('iterations')} iterations/run"
    )
    return printer(heading, details, warnings, labels, rows, stat)


def _text(heading, details, warnings, labels, rows, stat):
    lines = ['', heading, details, *warnings]
    lines.append(f'times are the median [min-max] over runs of per-run {stat}, in ms')
    lines.append('')
    table = [['scenario', *labels]]
    for scenario, cells in rows:
        row = [scenario]
        for cell in cells:
            if cell is None:
                row.append('-')
                continue
            median, lo, hi, n, speedup = cell
            text = f'{median:.2f} [{lo:.2f}-{hi:.2f}] n={n}'
            if speedup:
                text += f'  {speedup:.2f}x'
            row.append(text)
        table.append(row)
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    for row in table:
        lines.append('  '.join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())
    lines.append('')
    lines.append(f'(Nx = speed-up relative to {labels[0]})')
    return '\n'.join(lines) + '\n'


def _markdown(heading, details, warnings, labels, rows, stat):
    lines = [f'**{heading}**  ', f'{details}, median over runs of per-run {stat}', '']
    lines += [f'> {w}' for w in warnings]
    lines.append('| scenario | ' + ' | '.join(f'`{label}`' for label in labels) + ' |')
    lines.append('|---|' + '--:|' * len(labels))
    for scenario, cells in rows:
        texts = []
        for cell in cells:
            if cell is None:
                texts.append('-')
                continue
            median, _, _, n, speedup = cell
            text = f'{median:.1f} ms'
            if speedup:
                text += f' (**{speedup:.2f}x**)'
            texts.append(text)
        lines.append(f'| {scenario} | ' + ' | '.join(texts) + ' |')
    return '\n'.join(lines) + '\n\n'

"""Summarise JSONL results as text or markdown tables.

Runs are grouped by suite and scale. For each scenario and label: the median,
min and max over runs of each run's median value (or mean, with stat='mean'),
and the ratio of the first label's median to it, so higher is better.
Values are in each result's unit (ms if not given); all are lower-is-better.
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
        [meta.get('suite', 'store'), meta.get('counts') or meta.get('scale') or meta.get('scaleName')],
        sort_keys=True,
    )


def groups(runs: List[dict]) -> List[List[dict]]:
    """Split runs by suite and scale, ordered by suite then workflow size."""
    grouped = defaultdict(list)
    for run in runs:
        grouped[group_key(run)].append(run)

    def order(group):
        meta = group[0]['meta']
        counts = meta.get('counts') or {}
        return (meta.get('suite', 'store'), counts.get('tasks', 0), counts.get('cycles', 0))

    return sorted(grouped.values(), key=order)


def summarise(runs: List[dict], stat: str = 'p50', markdown: bool = False) -> str:
    """Return a summary of all groups of runs."""
    if not runs:
        return 'no results\n'
    printer = _markdown if markdown else _text
    return ''.join(_group(group, stat, printer) for group in groups(runs))


UNITS = {
    # unit: [(threshold, divisor, suffix), ...] choosing the first threshold below the value
    'ms': [(0, 1, 'ms')],
    's': [(0, 1, 's')],
    'bytes': [(1 << 30, 1 << 30, 'GiB'), (1 << 20, 1 << 20, 'MiB'), (1 << 10, 1 << 10, 'KiB'), (0, 1, 'B')],
}


def scale_unit(unit: str, value: float):
    """Return (divisor, suffix) to display values of this size in."""
    for threshold, divisor, suffix in UNITS.get(unit, [(0, 1, unit)]):
        if abs(value) >= threshold:
            return divisor, suffix
    return 1, unit


def _group(runs, stat, printer):
    warnings = []
    for key in ('vue', 'vueBuild', 'gc', 'iterations'):
        values = {json.dumps(r['meta'].get(key), sort_keys=True) for r in runs}
        if len(values) > 1:
            warnings.append(f'WARNING: runs differ in {key}: {sorted(values)}')

    labels = list(dict.fromkeys(r['meta']['label'] for r in runs))
    scenarios = list(dict.fromkeys(res['name'] for r in runs for res in r['results']))
    units = {}
    no_ratio = set()
    values = defaultdict(list)
    states = defaultdict(set)
    for r in runs:
        for res in r['results']:
            key = res['name'], r['meta']['label']
            units.setdefault(res['name'], res.get('unit', 'ms'))
            if res.get('ratio') is False:
                no_ratio.add(res['name'])
            states[key].add(res['state'])
            if res['state'] == 'completed':
                values[key].append(res[stat])

    # rows of (scenario, divisor, suffix, cells), where each cell is
    # (median, min, max, n, ratio), a state such as 'skipped', or None
    rows = []
    for scenario in scenarios:
        cells = []
        for label in labels:
            xs = values.get((scenario, label))
            if not xs:
                other = states.get((scenario, label))
                cells.append(sorted(other)[0] if other else None)
                continue
            median = statistics.median(xs)
            base = cells[0][0] if cells and isinstance(cells[0], tuple) else None
            ratio = base / median if base and median and scenario not in no_ratio else None
            cells.append((median, min(xs), max(xs), len(xs), ratio))
        medians = [c[0] for c in cells if isinstance(c, tuple)]
        divisor, suffix = scale_unit(units[scenario], medians[0] if medians else 0)
        rows.append((scenario, divisor, suffix, cells))

    meta = runs[0]['meta']
    suite = meta.get('suite', 'store')
    counts = meta.get('counts')
    if counts:
        heading = (
            f"{suite}: {counts['tasks']} tasks, {counts['jobs']} jobs,"
            f" {counts['families']} families, {counts['cycles']} cycles"
        )
        if 'edges' in counts:
            heading += f", {counts['edges']} edges"
    elif meta.get('scaleName') not in (None, 'default'):
        heading = f"{suite}: scale {meta['scaleName']}"
    else:
        heading = suite
    details = []
    if meta.get('vue'):
        details.append(f"vue {meta['vue']} ({meta.get('vueBuild')})")
    details.append(f"node {meta.get('node')}")
    if 'gc' in meta:
        details.append(f"forced gc: {meta['gc']}")
    if meta.get('iterations'):
        details.append(f"{meta['iterations']} iterations/run")
    details.append(f'{len(runs)} runs')
    return printer(heading, ', '.join(details), warnings, labels, rows, stat)


def _text(heading, details, warnings, labels, rows, stat):
    lines = ['', heading, details, *warnings]
    lines.append(f'values are the median [min-max] over runs of per-run {stat}')
    lines.append('')
    table = [['scenario', *labels]]
    for scenario, divisor, suffix, cells in rows:
        row = [f'{scenario} ({suffix})']
        for cell in cells:
            if not isinstance(cell, tuple):
                row.append(cell or '-')
                continue
            median, lo, hi, n, ratio = cell
            text = f'{median / divisor:.2f} [{lo / divisor:.2f}-{hi / divisor:.2f}] n={n}'
            if ratio:
                text += f'  {ratio:.2f}x'
            row.append(text)
        table.append(row)
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    for row in table:
        lines.append('  '.join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())
    lines.append('')
    lines.append(f'(Nx = {labels[0]} / value, so higher is better: faster or smaller)')
    return '\n'.join(lines) + '\n'


def _markdown(heading, details, warnings, labels, rows, stat):
    lines = [f'**{heading}**  ', f'{details}, median over runs of per-run {stat}', '']
    lines += [f'> {w}' for w in warnings]
    lines.append('| scenario | ' + ' | '.join(f'`{label}`' for label in labels) + ' |')
    lines.append('|---|' + '--:|' * len(labels))
    for scenario, divisor, suffix, cells in rows:
        texts = []
        for cell in cells:
            if not isinstance(cell, tuple):
                texts.append(cell or '-')
                continue
            median, _, _, n, ratio = cell
            text = f'{median / divisor:.1f} {suffix}'
            if ratio:
                text += f' (**{ratio:.2f}x**)'
            texts.append(text)
        lines.append(f'| {scenario} | ' + ' | '.join(texts) + ' |')
    return '\n'.join(lines) + '\n\n'

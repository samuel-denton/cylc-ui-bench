#!/usr/bin/env python3
"""Summarise cylc-ui-bench JSONL results.

For each scenario and label: the median, min and max over runs of each run's
median latency (or mean, with --stat mean), and the speed-up of each label
relative to the first one.

Usage: summarise.py [--markdown] [--stat p50|mean] RESULTS.jsonl [MORE.jsonl...]
"""
import argparse
import json
import statistics
import sys
from collections import defaultdict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('paths', nargs='+')
    parser.add_argument('--stat', choices=('p50', 'mean'), default='p50')
    parser.add_argument('--markdown', action='store_true')
    args = parser.parse_args()

    runs = [
        json.loads(line)
        for path in args.paths
        for line in open(path)
        if line.strip()
    ]
    if not runs:
        sys.exit('no results')

    for key in ('vue', 'vueBuild', 'gc', 'iterations', 'counts'):
        values = {
            json.dumps(r['meta'].get(key), sort_keys=True) for r in runs
        }
        if len(values) > 1:
            print(f'WARNING: runs differ in {key}: {sorted(values)}')

    labels = list(dict.fromkeys(r['meta']['label'] for r in runs))
    scenarios = list(dict.fromkeys(
        res['name'] for r in runs for res in r['results']
    ))
    values = defaultdict(list)
    for r in runs:
        for res in r['results']:
            if res['state'] == 'completed':
                values[res['name'], r['meta']['label']].append(res[args.stat])

    # rows of (scenario, [(median, min, max, n, speed-up) or None per label])
    base = labels[0]
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
    counts = meta['counts']
    heading = (
        f"{counts['tasks']} tasks, {counts['jobs']} jobs,"
        f" {counts['families']} families, {counts['cycles']} cycles"
    )
    details = (
        f"vue {meta['vue']} ({meta['vueBuild']}), node {meta['node']},"
        f" forced gc: {meta.get('gc', False)},"
        f" {meta['iterations']} iterations/run"
    )
    if args.markdown:
        print_markdown(heading, details, labels, rows, args.stat)
    else:
        print_text(heading, details, labels, rows, args.stat)


def print_text(heading, details, labels, rows, stat):
    print(f'\n{heading}\n{details}')
    print(f'times are the median [min-max] over runs of per-run {stat}, in ms\n')
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
        print('  '.join(cell.ljust(w) for cell, w in zip(row, widths)))
    print(f'\n(Nx = speed-up relative to {labels[0]})')


def print_markdown(heading, details, labels, rows, stat):
    print(f'**{heading}**  \n{details}, median over runs of per-run {stat}\n')
    print('| scenario | ' + ' | '.join(f'`{label}`' for label in labels) + ' |')
    print('|---|' + '--:|' * len(labels))
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
        print(f'| {scenario} | ' + ' | '.join(texts) + ' |')
    print()


if __name__ == '__main__':
    main()

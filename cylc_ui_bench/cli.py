"""Command line interface: cylc-ui-bench run|report|gui."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .runner import INSTALL_MODES
from .suites import SUITES

EXAMPLES = """\
examples:
  # compare a branch with upstream master (3 rounds, default scale)
  cylc-ui-bench run upstream/master my-branch

  # overnight: 4 sessions 30 minutes apart, at two scales
  nohup cylc-ui-bench run -n 4 -d 30 --scale 10x500x2 --scale 2x2500x2 \\
    upstream/master my-branch > overnight.out 2>&1 &
"""


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return value


def _non_negative_float(text: str) -> float:
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError('must not be negative')
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='cylc-ui-bench',
        description='Benchmark parts of the cylc-ui across git refs.',
    )
    sub = parser.add_subparsers(dest='command', metavar='COMMAND', required=True)

    def describe(s):
        scale = f'scale: {s.scale_help}' if s.scaled else '(not scaled)'
        return f'  {s.name:<10} {s.description}\n  {"":<10} {scale}; {s.default_iterations} iterations'

    suites = '\n'.join(describe(s) for s in SUITES.values())
    run = sub.add_parser(
        'run',
        help='benchmark git refs',
        description=(
            'Benchmark git refs of a cylc-ui checkout. Each ref is checked out'
            ' into a temporary worktree, and everything for the run goes in a new'
            ' timestamped directory under the results directory.'
        ),
        epilog=f'suites:\n{suites}\n\n{EXAMPLES}',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.add_argument(
        'refs', nargs='*', metavar='REF', default=['master', 'HEAD'],
        help='git refs to compare, the first is the baseline (default: master HEAD)',
    )
    run.add_argument(
        '-C', '--cylc-ui', metavar='DIR',
        help='cylc-ui checkout (default: $CYLC_UI, else the current directory'
             ' or ../cylc-ui next to this tool, if either is cylc-ui)',
    )
    run.add_argument(
        '-s', '--suite', dest='suites', action='append', choices=list(SUITES),
        help='suite to run, repeatable (default: all)',
    )
    run.add_argument(
        '--scale', dest='scales', action='append', metavar='SCALE',
        help="workload size, repeatable (default: each suite's default)",
    )
    run.add_argument(
        '-r', '--rounds', type=_positive_int, default=3,
        help='rounds per session, per scale, alternating ref order (default: 3)',
    )
    run.add_argument(
        '-i', '--iterations', type=_positive_int,
        help="timed iterations per scenario, per round (default: each suite's, see below)",
    )
    run.add_argument(
        '-n', '--sessions', type=_positive_int, default=1,
        help='number of sessions (default: 1)',
    )
    run.add_argument(
        '-d', '--delay', type=_non_negative_float, default=30, metavar='MINUTES',
        help='wait between sessions (default: 30)',
    )
    run.add_argument('--only', metavar='REGEX', help='only run scenarios matching REGEX')
    run.add_argument('-f', '--fetch', action='store_true', help='git fetch --all first')
    run.add_argument('-k', '--keep', action='store_true', help='keep the worktrees afterwards')
    run.add_argument(
        '--install', choices=INSTALL_MODES, default='auto',
        help="when to yarn install a ref's own node_modules, rather than use the"
             " checkout's: auto (if its yarn.lock or .yarnrc.yml differ), always"
             ' or never (default: auto)',
    )
    run.add_argument(
        '-o', '--results-dir', metavar='DIR',
        help='where to create the run directory'
             ' (default: $BENCH_RESULTS, else results/ in this tool)',
    )
    # used by the GUI, which creates the run directory itself
    run.add_argument('--run-dir', help=argparse.SUPPRESS)

    report = sub.add_parser(
        'report',
        help='summarise results',
        description=(
            'Print a summary of results. Given a single directory, also'
            ' (re)write its summary.txt, summary.md and report.html.'
        ),
    )
    report.add_argument(
        'paths', nargs='+', type=Path, metavar='PATH',
        help='run directory or .jsonl file',
    )
    report.add_argument(
        '--stat', choices=('p50', 'mean'), default='p50',
        help='per-run statistic to compare (default: p50)',
    )
    report.add_argument('--markdown', action='store_true', help='print markdown')

    gui = sub.add_parser(
        'gui',
        help='web GUI to start runs and view results',
        description=(
            'Serve a web GUI on 127.0.0.1 to configure and start runs and to'
            ' browse results, and open it in a browser. The URL includes an'
            ' access token, so only you can use it.'
        ),
    )
    gui.add_argument('-C', '--cylc-ui', metavar='DIR', help='cylc-ui checkout (as for run)')
    gui.add_argument(
        '-o', '--results-dir', metavar='DIR',
        help='results directory (default: $BENCH_RESULTS, else results/ in this tool)',
    )
    gui.add_argument(
        '-p', '--port', type=int, default=0,
        help='port to listen on (default: any free port)',
    )
    return parser


def cmd_run(args: argparse.Namespace) -> int:
    from .runner import Config, run
    config = Config(
        refs=args.refs,
        cylc_ui=args.cylc_ui,
        suites=args.suites or list(SUITES),
        scales=args.scales or [],
        rounds=args.rounds,
        iterations=args.iterations,
        sessions=args.sessions,
        delay=args.delay,
        only=args.only,
        fetch=args.fetch,
        keep=args.keep,
        install=args.install,
        results_dir=args.results_dir,
        run_dir=args.run_dir,
    )
    return run(config)


def cmd_report(args: argparse.Namespace) -> int:
    from .report import write_reports
    from .summarise import load, summarise
    files: List[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob('*.jsonl')))
        elif path.is_file():
            files.append(path)
        else:
            print(f'error: not found: {path}', file=sys.stderr)
            return 2
    if not files:
        print('error: no .jsonl results found', file=sys.stderr)
        return 2
    if len(args.paths) == 1 and args.paths[0].is_dir():
        write_reports(args.paths[0], files, args.stat)
    print(summarise(load(files), args.stat, markdown=args.markdown), end='')
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .server import serve
    return serve(args.cylc_ui, args.results_dir, args.port)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {'run': cmd_run, 'report': cmd_report, 'gui': cmd_gui}[args.command](args)
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())

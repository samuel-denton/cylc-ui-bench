"""Run benchmark suites across git refs of a cylc-ui checkout.

Each ref is resolved to a commit once and checked out into a temporary git
worktree (sharing node_modules with the main checkout), reused for the whole
run. For each session, scale and round, every ref is run in turn, alternating
the order (ABBA...) so machine noise is spread evenly. Sessions are separated
by a delay, e.g. to spread runs overnight.

Everything for a run goes in one directory:
  config.json    settings and resolved refs
  status.json    state and progress, updated as the run goes
  results.jsonl  one line per suite run
  run.log        output of every suite run
  summary.txt, summary.md, report.html   written at the end
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .report import write_reports
from .suites import COMMON_DIR, SUITES, Suite

SOURCE_ROOT = Path(__file__).resolve().parents[1]
WORKTREE_PARENT = 'run.'


class RunError(Exception):
    """A problem with the run's settings or environment."""


@dataclass
class Config:
    refs: List[str] = field(default_factory=lambda: ['master', 'HEAD'])
    cylc_ui: Optional[str] = None
    suites: List[str] = field(default_factory=lambda: list(SUITES))
    scales: List[str] = field(default_factory=list)
    rounds: int = 3
    iterations: int = 20
    sessions: int = 1
    delay: float = 30
    only: Optional[str] = None
    fetch: bool = False
    keep: bool = False
    results_dir: Optional[str] = None
    #: use this (new or empty) directory rather than creating one in results_dir
    run_dir: Optional[str] = None


def default_results_dir() -> Path:
    if os.environ.get('BENCH_RESULTS'):
        return Path(os.environ['BENCH_RESULTS'])
    if (SOURCE_ROOT / 'pyproject.toml').exists():
        return SOURCE_ROOT / 'results'
    return Path.cwd() / 'results'


def find_cylc_ui(given: Optional[str]) -> Path:
    """Use -C or $CYLC_UI, else the current directory or ../cylc-ui if either is cylc-ui."""
    explicit = given or os.environ.get('CYLC_UI')
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_dir():
            raise RunError(f'cylc-ui checkout not found: {path}')
        return path.resolve()
    for path in (Path.cwd(), SOURCE_ROOT.parent / 'cylc-ui'):
        if _is_cylc_ui(path):
            return path.resolve()
    raise RunError('cylc-ui checkout not found: use -C DIR or set $CYLC_UI')


def _is_cylc_ui(path: Path) -> bool:
    try:
        return json.loads((path / 'package.json').read_text()).get('name') == 'cylc-ui'
    except (OSError, ValueError):
        return False


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ['git', '-C', str(repo), *args],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise RunError(f"git {' '.join(args)} failed: {exc.stderr.strip()}") from None


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    os.replace(tmp, path)


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except OSError:
        return None


def make_run_dir(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    for n in range(100):
        path = base / (stamp if n == 0 else f'{stamp}-{n}')
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue
    raise RunError(f'could not create a run directory in {base}')


def _run_command(cmd: List[str], cwd: Path, env: Dict[str, str], log) -> int:
    """Run cmd in its own process group, killing the whole group if interrupted."""
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        return proc.wait()
    except BaseException:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
                proc.wait(timeout=10)
                break
            except ProcessLookupError:
                break
            except subprocess.TimeoutExpired:
                continue
        raise


def raise_interrupt(signum, frame):
    raise KeyboardInterrupt


class Runner:
    def __init__(self, config: Config):
        self.config = config
        self.suites: List[Suite] = []
        self.scales: Dict[str, List[str]] = {}
        self.refs: List[dict] = []
        self.worktrees: Dict[str, Path] = {}
        self.work: Optional[Path] = None
        self.status: dict = {}

    # -- setup -----------------------------------------------------------

    def validate(self) -> None:
        c = self.config
        if not c.refs:
            raise RunError('no refs given')
        for name in c.suites:
            if name not in SUITES:
                raise RunError(f'unknown suite: {name} (available: {", ".join(SUITES)})')
        self.suites = [SUITES[name] for name in dict.fromkeys(c.suites)]
        for suite in self.suites:
            if not suite.scaled:
                self.scales[suite.name] = ['default']
                continue
            scales = c.scales or list(suite.default_scales)
            for scale in scales:
                try:
                    suite.scale_env(scale)
                except ValueError as exc:
                    raise RunError(f'{suite.name}: {exc}') from None
            self.scales[suite.name] = scales
        for name in ('rounds', 'iterations', 'sessions'):
            if getattr(c, name) < 1:
                raise RunError(f'{name} must be at least 1')
        if c.delay < 0:
            raise RunError('delay must not be negative')

        self.repo = find_cylc_ui(c.cylc_ui)
        if not shutil.which('npx'):
            raise RunError('npx not found on PATH')
        if not (self.repo / 'node_modules').is_dir():
            raise RunError(f'no node_modules in {self.repo} (run yarn install)')
        self.node_version = subprocess.run(
            ['node', '--version'], capture_output=True, text=True, check=False,
        ).stdout.strip() or None

    def resolve_refs(self) -> None:
        if self.config.fetch:
            _git(self.repo, 'fetch', '--all', '--quiet')
        for ref in dict.fromkeys(self.config.refs):
            try:
                sha = _git(self.repo, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}')
            except RunError:
                raise RunError(f'unknown ref: {ref}') from None
            self.refs.append({'ref': ref, 'sha': sha, 'label': f'{ref}@{sha[:8]}'})

    def create_worktrees(self) -> None:
        tmp_base = Path(os.environ.get('BENCH_TMP') or Path.home() / '.cache' / 'cylc-ui-bench')
        tmp_base.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix=WORKTREE_PARENT, dir=tmp_base))
        for i, ref in enumerate(self.refs):
            path = self.work / f"{i}-{ref['ref'].replace('/', '_')}"
            _git(self.repo, 'worktree', 'add', '--detach', '--quiet', str(path), ref['sha'])
            (path / 'node_modules').symlink_to(self.repo / 'node_modules')
            if _read_bytes(path / 'yarn.lock') != _read_bytes(self.repo / 'yarn.lock'):
                self.log(
                    f"WARNING: {ref['label']} has a different yarn.lock to {self.repo},"
                    ' but runs with its node_modules'
                )
            bench_dir = path / 'tests/unit/_bench'
            shutil.copytree(COMMON_DIR, bench_dir / '_common', dirs_exist_ok=True)
            for suite in self.suites:
                target = path / suite.target()
                target.mkdir(parents=True, exist_ok=True)
                for file in suite.files():
                    shutil.copy2(file, target / file.name)
            self.worktrees[ref['label']] = path

    def cleanup(self) -> None:
        if self.work is None:
            return
        if self.config.keep:
            self.log(f'worktrees kept in {self.work}')
            return
        for path in self.worktrees.values():
            link = path / 'node_modules'
            if link.is_symlink():
                link.unlink()
        # on NFS, recently closed files can block removal for a few seconds
        for _ in range(6):
            shutil.rmtree(self.work, ignore_errors=True)
            subprocess.run(['git', '-C', str(self.repo), 'worktree', 'prune'], check=False)
            listed = subprocess.run(
                ['git', '-C', str(self.repo), 'worktree', 'list', '--porcelain'],
                capture_output=True, text=True, check=False,
            ).stdout
            if not self.work.exists() and str(self.work) not in listed:
                return
            time.sleep(5)
        self.log(f'WARNING: could not fully clean up {self.work}')

    # -- logging and status ----------------------------------------------

    def log(self, message: str) -> None:
        print(message, flush=True)
        with open(self.log_path, 'a') as log:
            log.write(message + '\n')

    def update_status(self, **changes) -> None:
        self.status.update(changes)
        _write_json(self.run_dir / 'status.json', self.status)

    # -- running ---------------------------------------------------------

    def run(self) -> int:
        """Run everything; return an exit code."""
        self.validate()
        self.resolve_refs()

        c = self.config
        if c.run_dir:
            self.run_dir = Path(c.run_dir).expanduser()
            self.run_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.run_dir = make_run_dir(Path(c.results_dir or default_results_dir()).expanduser())
        self.results_path = self.run_dir / 'results.jsonl'
        self.log_path = self.run_dir / 'run.log'
        jobs = [
            (session, suite, scale, round_, ref)
            for session in range(1, c.sessions + 1)
            for suite in self.suites
            for scale in self.scales[suite.name]
            for round_ in range(1, c.rounds + 1)
            for ref in (self.refs if round_ % 2 else self.refs[::-1])
        ]
        _write_json(self.run_dir / 'config.json', {
            **asdict(c),
            'cylc_ui': str(self.repo),
            'suites': [s.name for s in self.suites],
            'scales': self.scales,
            'refs': self.refs,
            'host': socket.gethostname(),
            'user': os.environ.get('USER'),
            'created': datetime.now().astimezone().isoformat(timespec='seconds'),
        })
        self.update_status(
            state='running', pid=os.getpid(), total=len(jobs), done=0, failed=0,
            current=None, started=datetime.now().astimezone().isoformat(timespec='seconds'),
            finished=None,
        )
        self.log(f'run directory: {self.run_dir}')
        self.log(f'cylc-ui: {self.repo}')
        self.log(f"refs: {', '.join(r['label'] for r in self.refs)}")

        previous = signal.signal(signal.SIGTERM, raise_interrupt)
        state = 'done'
        try:
            self.create_worktrees()
            self._run_jobs(jobs)
            if self.status['failed']:
                state = 'failed'
        except KeyboardInterrupt:
            state = 'interrupted'
            self.log('interrupted')
        except BaseException:
            state = 'error'
            raise
        finally:
            try:
                self.cleanup()
            finally:
                signal.signal(signal.SIGTERM, previous)
                self._finish(state)

        if state == 'interrupted':
            return 130
        if self.status['failed']:
            self.log(f"{self.status['failed']} run(s) failed, see {self.log_path}")
            return 1
        return 0

    def _run_jobs(self, jobs) -> None:
        c = self.config
        session = None
        for i, (job_session, suite, scale, round_, ref) in enumerate(jobs):
            if job_session != session:
                if session is not None and c.delay:
                    until = datetime.now() + timedelta(minutes=c.delay)
                    self.update_status(current=f"sleeping until {until:%H:%M}")
                    self.log(f'### sleeping {c.delay:g}m, until {until:%H:%M}')
                    time.sleep(c.delay * 60)
                session = job_session
                self.log(f'### session {session}/{c.sessions} ({datetime.now():%F %T})')

            description = (
                f'session {session}/{c.sessions}, {suite.name} {scale},'
                f" round {round_}/{c.rounds}: {ref['label']}"
            )
            self.update_status(current=description)
            self.log(f'=== [{i + 1}/{len(jobs)}] {description} ({datetime.now():%H:%M:%S})')
            env = {
                **os.environ,
                **suite.scale_env(scale),
                'NODE_ENV': 'production',
                'NO_COLOR': '1',
                'NODE_OPTIONS': ' '.join(filter(None, [os.environ.get('NODE_OPTIONS'), '--expose-gc'])),
                'BENCH_SUITE': suite.name,
                'BENCH_SCALE': scale,
                'BENCH_LABEL': ref['label'],
                'BENCH_SESSION': str(session),
                'BENCH_ROUND': str(round_),
                'BENCH_ITERATIONS': str(c.iterations),
                'BENCH_OUT': str(self.results_path),
            }
            if c.only:
                env['BENCH_ONLY'] = c.only
            worktree = self.worktrees[ref['label']]
            start = time.monotonic()
            with open(self.log_path, 'ab') as log:
                offset = log.tell()
                code = _run_command(suite.command(), worktree, env, log)
            elapsed = time.monotonic() - start
            with open(self.log_path, 'rb') as log:
                log.seek(offset)
                output = log.read().decode(errors='replace')
            if not code:
                try:
                    results = suite.collect(worktree, output, elapsed)
                except Exception as exc:
                    self.log(f'    could not collect results: {exc!r}')
                    code = -1
                else:
                    if results is not None:
                        self._record(suite, ref, session, round_, scale, results)
            if code:
                self.log(f'    FAILED (exit {code}, see log)')
                self.update_status(failed=self.status['failed'] + 1)
            self.update_status(done=i + 1)

    def _record(self, suite: Suite, ref: dict, session: int, round_: int, scale: str, results: List[dict]):
        """Append results collected by a command suite."""
        meta = {
            'suite': suite.name,
            'label': ref['label'],
            'session': session,
            'round': round_,
            'date': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'node': self.node_version,
            'scaleName': scale,
            'scale': None,
            'counts': None,
        }
        with open(self.results_path, 'a') as f:
            f.write(json.dumps({'meta': meta, 'results': results}) + '\n')

    def _finish(self, state: str) -> None:
        if self.results_path.exists() and self.results_path.stat().st_size:
            try:
                self.log(write_reports(self.run_dir, [self.results_path]))
                self.log(f"report: {self.run_dir / 'report.html'}")
            except Exception as exc:  # don't lose the run's state over a report bug
                self.log(f'WARNING: could not write reports: {exc}')
        self.update_status(
            state=state, current=None,
            finished=datetime.now().astimezone().isoformat(timespec='seconds'),
        )


def run(config: Config) -> int:
    try:
        return Runner(config).run()
    except RunError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2

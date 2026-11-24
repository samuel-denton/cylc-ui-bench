"""Benchmark suites.

Each suite is a subpackage of this one, defining a Suite subclass, and is
found automatically. Subpackages starting with "_" are not suites: _common
holds JS shared by all suites (harness.js, workflow.js), which is copied into
every worktree alongside the suites' own files.

There are two kinds of suite:

* vitest suites (the default): the suite's *.js files are copied into the
  worktree and run with vitest. The specs use _common/harness.js, which appends
  results to $BENCH_OUT.
* command suites: override command() to run something else and collect() to
  turn its output into results, which the runner records.

Either way, each suite run produces one line of results.jsonl:
  {"meta": {...}, "results": [{"name", "unit", "state", "p50", "mean", ...}]}
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

COMMON_DIR = Path(__file__).parent / '_common'
WORKFLOW_SCALE_HELP = 'CYCLESxTASKSxJOBS, e.g. 10x500x2 (tasks per cycle, jobs per task)'


def workflow_scale_env(scale: str) -> Dict[str, str]:
    """Env vars for a synthetic workflow scale (see _common/workflow.js)."""
    match = re.fullmatch(r'(\d+)x(\d+)x(\d+)', scale)
    if not match:
        raise ValueError(f'invalid scale: {scale!r} ({WORKFLOW_SCALE_HELP})')
    cycles, tasks, jobs = match.groups()
    return {'BENCH_CYCLES': cycles, 'BENCH_TASKS': tasks, 'BENCH_JOBS': jobs}


class Suite:
    """Base class for benchmark suites."""

    #: unique name, used on the command line and in results
    name = ''
    #: one-line description for --help and the GUI
    description = ''
    #: whether the suite runs at each of the run's (workflow) scales;
    #: suites that aren't scaled run once per round, ignoring --scale
    scaled = True
    #: scales to run when none are given
    default_scales = ('10x500x2',)
    scale_help = WORKFLOW_SCALE_HELP
    #: timed iterations per scenario when --iterations isn't given
    default_iterations = 20
    #: extra arguments for vitest, e.g. ('--pool=forks',) for suites that
    #: need a separate process (heavy rendering, clear out-of-memory errors)
    vitest_args: Tuple[str, ...] = ()

    @property
    def path(self) -> Path:
        """Directory containing the suite's files."""
        return Path(inspect.getfile(type(self))).parent

    def files(self) -> List[Path]:
        """Files to copy into the worktree: by default the suite's *.js."""
        return sorted(self.path.glob('*.js'))

    def target(self) -> str:
        """Directory within the worktree that the suite's files go in."""
        return f'tests/unit/_bench/{self.name}'

    def scale_env(self, scale: str) -> Dict[str, str]:
        """Return env vars for a scale; raise ValueError if it is invalid."""
        return workflow_scale_env(scale) if self.scaled else {}

    def command(self) -> List[str]:
        """Command to run the suite from the worktree root."""
        return ['npx', 'vitest', 'run', f'{self.target()}/', '--silent=false', *self.vitest_args]

    def collect(self, worktree: Path, output: str, elapsed: float) -> Optional[List[dict]]:
        """Results for a command suite, from its output and elapsed time (s).

        Return None for vitest suites, whose specs record their own results.
        """
        return None


def _discover() -> Dict[str, Suite]:
    suites = {}
    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith('_'):
            continue
        mod = importlib.import_module(f'{__name__}.{module.name}')
        for obj in vars(mod).values():
            if inspect.isclass(obj) and issubclass(obj, Suite) and obj.__module__ == mod.__name__:
                suite = obj()
                if suite.name in suites:
                    raise RuntimeError(f'duplicate suite name: {suite.name}')
                suites[suite.name] = suite
    return dict(sorted(suites.items()))


SUITES = _discover()

"""Benchmark suites.

A suite is a set of vitest spec files that are copied into each cylc-ui
worktree and run there. Each spec appends one JSON line per run to the file
named by $BENCH_OUT: {"meta": {...}, "results": [{"name": ..., ...}]}.

To add a suite, create a subpackage defining a Suite subclass and register an
instance of it in SUITES below.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Dict, List, Tuple


class Suite:
    """Base class for benchmark suites."""

    #: unique name, used on the command line and in results
    name = ''
    #: one-line description for --help
    description = ''
    #: files in the suite's directory to copy into the worktree
    files: Tuple[str, ...] = ()
    #: scales to run when none are given
    default_scales: Tuple[str, ...] = ('default',)
    #: help text describing the scale format
    scale_help = ''

    @property
    def path(self) -> Path:
        """Directory containing the suite's files."""
        return Path(inspect.getfile(type(self))).parent

    def target(self) -> str:
        """Directory within the worktree that the suite's files go in."""
        return f'tests/unit/_bench/{self.name}'

    def scale_env(self, scale: str) -> Dict[str, str]:
        """Return env vars for a scale; raise ValueError if it is invalid."""
        return {}

    def command(self) -> List[str]:
        """Command to run the suite from the worktree root."""
        return ['npx', 'vitest', 'run', f'{self.target()}/', '--silent=false']


def _load() -> Dict[str, Suite]:
    from .store import StoreSuite
    return {suite.name: suite for suite in (StoreSuite(),)}


SUITES = _load()

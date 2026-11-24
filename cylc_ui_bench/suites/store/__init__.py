"""Workflows store mutations against a synthetic workflow."""
from __future__ import annotations

import re
from typing import Dict

from .. import Suite


class StoreSuite(Suite):
    name = 'store'
    description = 'workflows store mutations (load, spawn, update, prune, remove)'
    files = ('store.bench.spec.js', 'deltas.js')
    default_scales = ('10x500x2',)
    scale_help = 'CYCLESxTASKSxJOBS, e.g. 10x500x2 (tasks per cycle, jobs per task)'

    def scale_env(self, scale: str) -> Dict[str, str]:
        match = re.fullmatch(r'(\d+)x(\d+)x(\d+)', scale)
        if not match:
            raise ValueError(f'invalid scale for {self.name}: {scale!r} ({self.scale_help})')
        cycles, tasks, jobs = match.groups()
        return {'BENCH_CYCLES': cycles, 'BENCH_TASKS': tasks, 'BENCH_JOBS': jobs}

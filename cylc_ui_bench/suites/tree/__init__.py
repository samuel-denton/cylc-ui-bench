"""Tree view rendering in happy-dom."""
from .. import Suite


class TreeSuite(Suite):
    name = 'tree'
    description = 'Tree view rendering (mount, expand jobs, update, filter) and memory, in happy-dom'
    default_iterations = 5
    vitest_args = ('--pool=forks',)

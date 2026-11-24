"""Graph view layout: dot code and Graphviz layout, without rendering."""
from .. import Suite


class GraphSuite(Suite):
    name = 'graph'
    description = 'Graph view layout (dot code, Graphviz layout and processing), without rendering'
    default_iterations = 5
    vitest_args = ('--pool=forks',)

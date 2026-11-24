"""Workflows store mutations against a synthetic workflow."""
from .. import Suite


class StoreSuite(Suite):
    name = 'store'
    description = 'workflows store mutations (load, spawn, update, prune, remove) and memory'

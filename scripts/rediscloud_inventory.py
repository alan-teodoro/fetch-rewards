"""Compatibility imports for state reconciliation; implementation lives in rediscloud.inventory."""

from rediscloud.inventory import attributes, destroy_variables, removed_entries
from rediscloud.agent_memory import agent_destroy_variables
from rediscloud.stacks import RESOURCES

__all__ = [
    "attributes",
    "destroy_variables",
    "removed_entries",
    "agent_destroy_variables",
    "RESOURCES",
]

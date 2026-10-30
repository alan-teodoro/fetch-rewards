"""Compatibility imports for state reconciliation; implementation lives in rediscloud.inventory."""

from rediscloud.agent_memory_state import agent_destroy_variables
from rediscloud.inventory import attributes, destroy_variables, removed_entries
from rediscloud.stacks import RESOURCES

__all__ = [
    "RESOURCES",
    "agent_destroy_variables",
    "attributes",
    "destroy_variables",
    "removed_entries",
]

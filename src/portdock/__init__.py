"""
portdock - Interactive Port Conflict Resolver & Ghost Process Dissector.
"""

__version__ = "0.1.0"

from .models import PortInfo, BindType, ProcessTreeNode, KillReport
from .scanner import scan_listening_ports, get_port_details
from .killer import terminate_port

__all__ = [
    "__version__",
    "PortInfo",
    "BindType",
    "ProcessTreeNode",
    "KillReport",
    "scan_listening_ports",
    "get_port_details",
    "terminate_port",
]

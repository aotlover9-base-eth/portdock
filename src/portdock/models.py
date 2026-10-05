"""
Data models and Enums for portdock.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import List, Optional


class BindType(str, Enum):
    LOCAL = "local"
    PUBLIC = "public"
    SPECIFIC = "specific"

    @property
    def badge(self) -> str:
        if self == BindType.LOCAL:
            return "[green]LOCAL[/green]"
        elif self == BindType.PUBLIC:
            return "[bold red]PUBLIC[/bold red]"
        return "[yellow]SPECIFIC[/yellow]"

    @property
    def badge_full(self) -> str:
        if self == BindType.LOCAL:
            return "[green]🔒 Localhost Only (127.0.0.1)[/green]"
        elif self == BindType.PUBLIC:
            return "[bold red]🌐 Public / All Interfaces (0.0.0.0)[/bold red]"
        return "[yellow]📡 Interface Specific[/yellow]"


def detect_bind_type(ip: str) -> BindType:
    clean_ip = ip.strip().lower()
    if clean_ip in ("127.0.0.1", "::1", "localhost"):
        return BindType.LOCAL
    if clean_ip in ("0.0.0.0", "::", "*", ""):
        return BindType.PUBLIC
    return BindType.SPECIFIC


@dataclass
class ProcessTreeNode:
    pid: int
    name: str
    cmdline: str
    user: str = ""
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    children: List[ProcessTreeNode] = field(default_factory=list)


@dataclass
class PortInfo:
    port: int
    proto: str # "tcp" or "udp"
    bind_ip: str
    bind_type: BindType
    pid: Optional[int] = None
    name: str = "Unknown"
    user: str = ""
    cmdline: str = ""
    cwd: str = ""
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    created_time: float = 0.0
    container_name: Optional[str] = None
    tree_chain: str = ""
    process_tree: Optional[ProcessTreeNode] = None

    @property
    def display_name(self) -> str:
        if self.container_name:
            return f"{self.name} [cyan][{self.container_name}][/cyan]"
        return self.name

    @property
    def formatted_memory(self) -> str:
        if self.memory_mb <= 0:
            return "-"
        if self.memory_mb >= 1024:
            return f"{self.memory_mb / 1024:.1f} GB"
        return f"{self.memory_mb:.1f} MB"

    @property
    def formatted_uptime(self) -> str:
        if self.created_time <= 0:
            return "-"
        elapsed = max(0, int(time.time() - self.created_time))
        hours, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        if hours > 24:
            days = hours // 24
            return f"{days}d {hours % 24}h"
        if hours > 0:
            return f"{hours}h {mins:02d}m"
        if mins > 0:
            return f"{mins}m {secs:02d}s"
        return f"{secs}s"

    @property
    def short_cmdline(self) -> str:
        if not self.cmdline:
            return self.name
        # Strip long path from the executable
        parts = self.cmdline.split()
        if parts:
            exe = parts[0].split("/")[-1]
            rest = " ".join(parts[1:])
            full = f"{exe} {rest}".strip()
            return full[:75] + ("..." if len(full) > 75 else "")
        return self.cmdline[:75]


@dataclass
class KillReport:
    port: int
    pids_targeted: List[int]
    pids_killed: List[int]
    killed_process_names: List[str]
    tree_killed: bool
    success: bool
    freed: bool
    error_message: str = ""

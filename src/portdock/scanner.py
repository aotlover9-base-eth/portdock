"""
Port scanner and process tree inspector for portdock.
"""

from __future__ import annotations
import errno
import os
import shutil
import socket
import subprocess
from typing import Dict, List, Optional, Set, Tuple
import psutil

from .models import BindType, PortInfo, ProcessTreeNode, detect_bind_type

SHELL_AND_INIT_NAMES: Set[str] = {
    "systemd",
    "init",
    "bash",
    "zsh",
    "fish",
    "sh",
    "dash",
    "tcsh",
    "csh",
    "ksh",
    "login",
    "sshd",
    "tmux",
    "tmux: server",
    "screen",
    "gnome-terminal",
    "gnome-terminal-server",
    "alacritty",
    "kitty",
    "wezterm",
    "wezterm-gui",
    "konsole",
    "ptyxis",
    "xterm",
    "terminator",
    "Xorg",
    "wayland",
    "gnome-shell",
    "plasmashell",
    "kwin_wayland",
    "kwin_x11",
    "containerd",
    "dockerd",
    "pytest",
    "pytest-3",
    "code",
    "code-server",
    "vscode",
    "cursor",
    "antigravity",
    "antigravity-ide",
}


def is_shell_or_init(proc_or_name: psutil.Process | str) -> bool:
    """Determine if a process is a shell, init daemon, desktop supervisor, or test harness."""
    if isinstance(proc_or_name, str):
        clean_name = proc_or_name.strip().lower()
        return clean_name in SHELL_AND_INIT_NAMES or clean_name.startswith("systemd")

    try:
        clean_name = proc_or_name.name().strip().lower()
        if clean_name in SHELL_AND_INIT_NAMES or clean_name.startswith("systemd"):
            return True

        # Check executable basename
        try:
            exe = proc_or_name.exe()
            if exe and os.path.basename(exe).lower() in SHELL_AND_INIT_NAMES:
                return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        # Check for pytest or test harness as the primary command/module
        cmdline_parts = [arg.lower() for arg in proc_or_name.cmdline()]
        if any(part in ("pytest", "py.test") for part in cmdline_parts):
            return True
        if len(cmdline_parts) >= 3 and cmdline_parts[1] == "-m" and cmdline_parts[2] in ("pytest", "unittest"):
            return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return False


def _get_current_process_protection_set() -> Set[int]:
    """Return PIDs of current process and all its ancestors to prevent self-termination."""
    pids = {os.getpid()}
    try:
        for p in psutil.Process().parents():
            pids.add(p.pid)
    except Exception:
        pass
    return pids


def find_root_supervisor(proc: psutil.Process) -> psutil.Process:
    """
    Traverse parent hierarchy upwards to find the top-level supervisor
    just below the user's interactive shell or systemd.
    Useful for killing dev runners (e.g. nodemon, npm run dev, cargo watch).
    """
    try:
        parents = proc.parents()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return proc

    protected_pids = _get_current_process_protection_set()

    # parents is ordered [parent, grandparent, great-grandparent, ...]
    candidate = proc
    for parent in parents:
        try:
            if parent.pid in protected_pids or parent.pid <= 1:
                break
            if is_shell_or_init(parent):
                break
            candidate = parent
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break

    return candidate


def get_supervisor_chain(proc: psutil.Process) -> str:
    """
    Generate a concise breadcrumb trail from top supervisor to target process.
    Example: npm (4990) -> nodemon (4995) -> node (5000)
    """
    try:
        parents = proc.parents()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return f"{proc.name()} ({proc.pid})"

    protected_pids = _get_current_process_protection_set()

    chain_parts: List[str] = []
    for parent in reversed(parents):
        try:
            if parent.pid in protected_pids or parent.pid <= 1:
                continue
            if is_shell_or_init(parent):
                continue
            chain_parts.append(f"{parent.name()} ({parent.pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    try:
        chain_parts.append(f"{proc.name()} ({proc.pid})")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        chain_parts.append(f"PID {proc.pid}")

    return " -> ".join(chain_parts) if chain_parts else f"{proc.pid}"


def build_process_tree(proc: psutil.Process) -> ProcessTreeNode:
    """
    Recursively build a ProcessTreeNode hierarchy starting at proc.
    """
    try:
        pid = proc.pid
    except Exception:
        pid = 0

    try:
        name = proc.name()
    except Exception:
        name = f"PID {pid}" if pid else "<terminated>"

    try:
        cmdline = " ".join(proc.cmdline())
    except Exception:
        cmdline = ""

    try:
        user = proc.username()
    except Exception:
        user = ""

    try:
        mem = proc.memory_info().rss / (1024 * 1024)
    except Exception:
        mem = 0.0

    try:
        cpu = proc.cpu_percent(interval=0.0)
    except Exception:
        cpu = 0.0

    children_nodes: List[ProcessTreeNode] = []
    try:
        children = proc.children(recursive=False)
        for child in children:
            children_nodes.append(build_process_tree(child))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return ProcessTreeNode(
        pid=pid,
        name=name,
        cmdline=cmdline,
        user=user,
        memory_mb=mem,
        cpu_percent=cpu,
        children=children_nodes,
    )


def get_docker_container(port: int) -> Optional[str]:
    """
    Query Docker daemon to see if a published port maps to an active container.
    Returns e.g. "my-postgres (postgres:15-alpine)" or None.
    """
    if not shutil.which("docker"):
        return None

    try:
        res = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"publish={port}",
                "--format",
                "{{.Names}} ({{.Image}})",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.35,
        )
        out = res.stdout.strip()
        if out:
            # First line if multiple
            return out.splitlines()[0]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        pass

    return None


def is_port_free(port: int, proto: str = "tcp") -> bool:
    """
    Verify whether a port is released and available for binding.
    Handles non-root privileged ports (<1024) and non-blocking probes.
    """
    clean_proto = proto.lower()

    # Check if psutil sees an active listener
    try:
        conns = psutil.net_connections(kind="inet")
        for c in conns:
            if c.laddr and getattr(c.laddr, "port", None) == port:
                if clean_proto == "tcp" and c.status == psutil.CONN_LISTEN:
                    return False
                elif clean_proto == "udp":
                    return False
    except (psutil.AccessDenied, PermissionError):
        pass

    if clean_proto == "tcp":
        for host in ("0.0.0.0", "127.0.0.1"):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((host, port))
            except OSError as err:
                if err.errno == errno.EACCES:
                    # Non-root permission denied on privileged port (<1024). Probe with connect.
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                            probe.settimeout(0.05)
                            probe.connect(("127.0.0.1", port))
                            return False  # Successfully connected -> active socket
                    except OSError as probe_err:
                        if probe_err.errno in (errno.ECONNREFUSED, errno.ENETUNREACH, errno.ETIMEDOUT):
                            continue
                        return False
                elif err.errno == errno.EADDRINUSE:
                    return False
                else:
                    return False
        return True
    else:
        for host in ("0.0.0.0", "127.0.0.1"):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.bind((host, port))
            except OSError as err:
                if err.errno == errno.EACCES:
                    continue
                return False
        return True


def get_pids_for_port(port: int, proto: str = "tcp") -> List[int]:
    """Return all PIDs associated with listening sockets on the specified port."""
    pids: Set[int] = set()
    clean_proto = proto.lower()
    kind = "inet"
    if clean_proto == "tcp":
        kind = "tcp"
    elif clean_proto == "udp":
        kind = "udp"

    try:
        conns = psutil.net_connections(kind=kind)
        for c in conns:
            if c.laddr and getattr(c.laddr, "port", None) == port:
                if clean_proto == "tcp" and c.status != psutil.CONN_LISTEN:
                    continue
                if c.pid is not None:
                    pids.add(c.pid)
    except (psutil.AccessDenied, PermissionError):
        pass

    return sorted(pids)


def scan_listening_ports(proto_filter: Optional[str] = None) -> List[PortInfo]:
    """
    Scan all open listening sockets (TCP and UDP) on the system.
    Returns a sorted list of PortInfo objects.
    """
    kind = "inet"
    if proto_filter:
        p = proto_filter.lower()
        if p == "tcp":
            kind = "tcp"
        elif p == "udp":
            kind = "udp"

    try:
        connections = psutil.net_connections(kind=kind)
    except (psutil.AccessDenied, PermissionError):
        # Fallback to current user connections
        connections = []

    # Map of (port, proto) -> PortInfo
    port_map: Dict[Tuple[int, str], PortInfo] = {}

    for conn in connections:
        # We only care about listening sockets or UDP bound sockets
        proto = "tcp" if conn.type == socket.SOCK_STREAM else "udp"
        if proto == "tcp" and conn.status != psutil.CONN_LISTEN:
            continue

        if not conn.laddr or not hasattr(conn.laddr, "port"):
            continue

        port = conn.laddr.port
        ip = getattr(conn.laddr, "ip", "0.0.0.0")
        bind_type = detect_bind_type(ip)
        pid = conn.pid

        # If already recorded with public binding, don't downgrade to local
        key = (port, proto)
        if key in port_map and port_map[key].bind_type == BindType.PUBLIC:
            # If current is local, skip updating bind_type
            pass
        elif key in port_map and bind_type == BindType.PUBLIC:
            port_map[key].bind_type = BindType.PUBLIC
            port_map[key].bind_ip = ip

        if key in port_map and port_map[key].pid is not None:
            # Already mapped to a process
            continue

        # Process metadata
        name = "Unknown"
        user = ""
        cmdline = ""
        cwd = ""
        created_time = 0.0
        memory_mb = 0.0
        cpu_percent = 0.0
        chain = ""
        proc_tree: Optional[ProcessTreeNode] = None

        if pid is not None:
            try:
                proc = psutil.Process(pid)
                try:
                    name = proc.name()
                except Exception:
                    name = f"PID {pid}"
                try:
                    cmdline = " ".join(proc.cmdline())
                except Exception:
                    cmdline = ""
                try:
                    user = proc.username()
                except Exception:
                    user = ""
                try:
                    cwd = proc.cwd()
                except Exception:
                    cwd = ""
                try:
                    created_time = proc.create_time()
                except Exception:
                    created_time = 0.0
                try:
                    mem_info = proc.memory_info()
                    memory_mb = mem_info.rss / (1024 * 1024)
                except Exception:
                    memory_mb = 0.0
                try:
                    cpu_percent = proc.cpu_percent(interval=0.0)
                except Exception:
                    cpu_percent = 0.0
                try:
                    chain = get_supervisor_chain(proc)
                except Exception:
                    chain = ""
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                name = "<process exited>"
        else:
            name = "[Root / System]"
            user = "root"
            cmdline = "[Protected System Socket]"

        # Docker container check if docker-proxy or docker
        container_name = None
        if name == "docker-proxy" or "docker" in cmdline.lower():
            container_name = get_docker_container(port)

        info = PortInfo(
            port=port,
            proto=proto,
            bind_ip=ip,
            bind_type=bind_type,
            pid=pid,
            name=name,
            user=user,
            cmdline=cmdline,
            cwd=cwd,
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
            created_time=created_time,
            container_name=container_name,
            tree_chain=chain,
            process_tree=proc_tree,
        )
        port_map[key] = info

    # Sort ports ascending
    sorted_ports = sorted(port_map.values(), key=lambda p: (p.port, p.proto))
    return sorted_ports


def get_port_details(port: int, proto: Optional[str] = None) -> Optional[PortInfo]:
    """
    Retrieve in-depth information for a single port, including the full process tree.
    """
    ports = scan_listening_ports(proto_filter=proto)
    matches = [p for p in ports if p.port == port]
    if not matches:
        return None

    # Pick the first matching (prefer TCP if both)
    selected = matches[0]
    for m in matches:
        if m.proto == "tcp":
            selected = m
            break

    # Build detailed process tree if PID is available
    if selected.pid is not None:
        try:
            proc = psutil.Process(selected.pid)
            selected.process_tree = build_process_tree(proc)
            # Recheck docker container if not already found
            if not selected.container_name:
                selected.container_name = get_docker_container(port)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return selected

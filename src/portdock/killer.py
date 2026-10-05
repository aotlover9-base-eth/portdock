"""
Process termination and port freeing engine for portdock.
"""

from __future__ import annotations
import os
import signal
import time
from typing import List, Optional, Set
import psutil

from .models import KillReport
from .scanner import find_root_supervisor, get_pids_for_port, is_port_free, scan_listening_ports


def _get_protected_pids() -> Set[int]:
    pids = {os.getpid()}
    try:
        for p in psutil.Process().parents():
            pids.add(p.pid)
    except Exception:
        pass
    return pids


def _collect_pids_to_kill(target_proc: psutil.Process, kill_tree: bool = False) -> List[psutil.Process]:
    """
    Collect the target processes.
    If kill_tree is True, traverses to root supervisor and collects it and all descendants.
    Otherwise, collects target process and its direct children.
    """
    procs: List[psutil.Process] = []
    seen: Set[int] = set()
    protected = _get_protected_pids()

    if kill_tree:
        root = find_root_supervisor(target_proc)
        try:
            if root.pid not in seen and root.pid not in protected and root.pid > 1:
                procs.append(root)
                seen.add(root.pid)
            for child in root.children(recursive=True):
                if child.pid not in seen and child.pid not in protected and child.pid > 1:
                    procs.append(child)
                    seen.add(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    else:
        try:
            if target_proc.pid not in seen and target_proc.pid not in protected and target_proc.pid > 1:
                procs.append(target_proc)
                seen.add(target_proc.pid)
            # Also terminate any child workers
            for child in target_proc.children(recursive=True):
                if child.pid not in seen and child.pid not in protected and child.pid > 1:
                    procs.append(child)
                    seen.add(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return procs


def terminate_port(
    port: int,
    force: bool = False,
    kill_tree: bool = False,
    proto: str = "tcp",
    timeout: float = 1.0,
) -> KillReport:
    """
    Terminate process(es) holding the given port and verify release.
    """
    active_pids = set(get_pids_for_port(port, proto=proto))
    ports = scan_listening_ports(proto_filter=proto)
    matching = [p for p in ports if p.port == port]
    for m in matching:
        if m.pid is not None:
            active_pids.add(m.pid)

    if not active_pids:
        # Check if already free
        if is_port_free(port, proto):
            return KillReport(
                port=port,
                pids_targeted=[],
                pids_killed=[],
                killed_process_names=[],
                tree_killed=kill_tree,
                success=True,
                freed=True,
            )
        else:
            return KillReport(
                port=port,
                pids_targeted=[],
                pids_killed=[],
                killed_process_names=[],
                tree_killed=kill_tree,
                success=False,
                freed=False,
                error_message=f"Port {port} is active but no listening process could be identified (likely kernel or permission restricted).",
            )

    # Check for root/permission issues
    unresolved_root = [p for p in matching if p.pid is None]
    if unresolved_root and not active_pids:
        return KillReport(
            port=port,
            pids_targeted=[],
            pids_killed=[],
            killed_process_names=[],
            tree_killed=kill_tree,
            success=False,
            freed=False,
            error_message=f"Port {port} is held by a system service or root process. Run with sudo: sudo portdock kill {port}",
        )

    targeted_pids: List[int] = []
    killed_pids: List[int] = []
    killed_names: List[str] = []
    all_target_procs: List[psutil.Process] = []

    for pid in sorted(active_pids):
        try:
            p = psutil.Process(pid)
            all_target_procs.extend(_collect_pids_to_kill(p, kill_tree=kill_tree))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Deduplicate processes preserving order
    unique_procs: List[psutil.Process] = []
    seen_pids: Set[int] = set()
    for proc in all_target_procs:
        if proc.pid not in seen_pids:
            seen_pids.add(proc.pid)
            unique_procs.append(proc)
            targeted_pids.append(proc.pid)

    if not unique_procs:
        freed = is_port_free(port, proto)
        return KillReport(
            port=port,
            pids_targeted=[],
            pids_killed=[],
            killed_process_names=[],
            tree_killed=kill_tree,
            success=freed,
            freed=freed,
            error_message="" if freed else f"Could not access processes on port {port}.",
        )

    # Phase 1: Graceful termination or immediate force
    sig = signal.SIGKILL if force else signal.SIGTERM
    for proc in unique_procs:
        try:
            name = proc.name()
            killed_names.append(f"{name} (PID: {proc.pid})")
            proc.send_signal(sig)
        except (psutil.NoSuchProcess, ProcessLookupError):
            pass
        except (psutil.AccessDenied, PermissionError):
            return KillReport(
                port=port,
                pids_targeted=targeted_pids,
                pids_killed=killed_pids,
                killed_process_names=killed_names,
                tree_killed=kill_tree,
                success=False,
                freed=False,
                error_message=f"Access denied terminating PID {proc.pid}. Try running with sudo: sudo portdock kill {port}",
            )

    # Phase 2: Wait up to 250ms for SIGTERM, then escalate to SIGKILL if not force
    if not force:
        start_wait = time.time()
        while time.time() - start_wait < 0.25:
            alive = [p for p in unique_procs if p.is_running()]
            if not alive:
                break
            time.sleep(0.02)

        # Escalate remaining alive processes to SIGKILL
        for proc in unique_procs:
            try:
                if proc.is_running():
                    proc.send_signal(signal.SIGKILL)
            except (psutil.NoSuchProcess, ProcessLookupError, psutil.AccessDenied):
                pass

    # Record successfully killed PIDs
    for pid in targeted_pids:
        try:
            p = psutil.Process(pid)
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                killed_pids.append(pid)
        except (psutil.NoSuchProcess, ProcessLookupError):
            killed_pids.append(pid)

    # Phase 3: Verify socket release
    freed = False
    start_verify = time.time()
    while time.time() - start_verify < timeout:
        if is_port_free(port, proto):
            freed = True
            break
        time.sleep(0.03)

    return KillReport(
        port=port,
        pids_targeted=targeted_pids,
        pids_killed=killed_pids,
        killed_process_names=killed_names,
        tree_killed=kill_tree,
        success=freed and (len(killed_pids) > 0 or len(targeted_pids) == 0),
        freed=freed,
        error_message="" if freed else f"Killed processes {killed_pids}, but port {port} socket is still bound (may be in TIME_WAIT).",
    )

"""
CLI entry point and command router for portdock.
"""

from __future__ import annotations
import argparse
import json
import sys
import time
from typing import List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .killer import terminate_port
from .models import BindType, KillReport, PortInfo
from .scanner import get_port_details, is_port_free, scan_listening_ports
from .tui import create_ports_table, render_kill_report, render_port_detail_card, run_interactive_tui

console = Console()
err_console = Console(stderr=True)


def parse_port(arg: str) -> int:
    """
    Parse a port string into an integer.
    Supports formats: '3000', ':3000', 'localhost:3000', 'http://localhost:3000', '3000/tcp', '[::1]:8080'.
    """
    cleaned = arg.strip()
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    if "?" in cleaned:
        cleaned = cleaned.split("?", 1)[0]
    if "#" in cleaned:
        cleaned = cleaned.split("#", 1)[0]
    if "/" in cleaned:
        cleaned = cleaned.split("/")[0]
    if "]" in cleaned:
        cleaned = cleaned.split("]")[-1]
    if ":" in cleaned:
        cleaned = cleaned.split(":")[-1]
    cleaned = cleaned.strip().lstrip(":")

    if not cleaned.isdigit():
        raise ValueError(f"Invalid port: '{arg}' (must be a valid integer between 1 and 65535)")
    port_num = int(cleaned)
    if not (1 <= port_num <= 65535):
        raise ValueError(f"Port {port_num} out of valid range (1 - 65535)")
    return port_num


def print_banner():
    banner = Text()
    banner.append("⚡ PORTDOCK ", style="bold cyan")
    banner.append(f"v{__version__} ", style="bold dim")
    banner.append("- Interactive Port Conflict Resolver & Ghost Process Dissector", style="dim")
    console.print(banner)


def cmd_list(args):
    """List open listening ports."""
    proto = None
    if args.tcp and not args.udp:
        proto = "tcp"
    elif args.udp and not args.tcp:
        proto = "udp"

    ports = scan_listening_ports(proto_filter=proto)

    if args.local and not args.public:
        ports = [p for p in ports if p.bind_type == BindType.LOCAL]
    elif args.public and not args.local:
        ports = [p for p in ports if p.bind_type == BindType.PUBLIC]

    if args.json:
        data = [
            {
                "port": p.port,
                "proto": p.proto,
                "bind_ip": p.bind_ip,
                "bind_type": p.bind_type.value,
                "pid": p.pid,
                "process": p.name,
                "user": p.user,
                "memory_mb": round(p.memory_mb, 2),
                "cpu_percent": round(p.cpu_percent, 2),
                "uptime_seconds": round(time.time() - p.created_time, 2) if p.created_time > 0 else 0,
                "container": p.container_name,
                "cmdline": p.cmdline,
                "supervisor_chain": p.tree_chain,
            }
            for p in ports
        ]
        print(json.dumps(data, indent=2))
        return

    print_banner()
    if not ports:
        console.print("\n[yellow]No listening ports matching criteria found.[/yellow]\n")
        return

    table = create_ports_table(ports)
    console.print(table)
    console.print(f"\n[dim]Total: {len(ports)} listening port(s)[/dim]\n")


def cmd_dissect(port_num: int, proto: Optional[str] = None):
    """Inspect a single port in detail."""
    details = get_port_details(port_num, proto=proto)
    if not details:
        if is_port_free(port_num, proto=proto or "tcp"):
            console.print(f"\n[bold green]✓ Port {port_num} is currently FREE (not bound to any process).[/bold green]\n")
        else:
            console.print(f"\n[bold red]✗ Port {port_num} is active but inaccessible or system-protected.[/bold red]\n")
        return

    panel = render_port_detail_card(details)
    console.print(panel)


def cmd_kill(args):
    """Terminate process(es) holding specified port(s)."""
    ports_to_kill: List[int] = []
    for item in args.ports:
        try:
            ports_to_kill.append(parse_port(item))
        except ValueError as e:
            err_console.print(f"[bold red]Error:[/bold red] {e}")
            sys.exit(1)

    all_freed = True

    for p in ports_to_kill:
        report = terminate_port(
            port=p,
            force=args.force,
            kill_tree=args.tree,
            proto=args.proto,
        )

        if not report.freed:
            all_freed = False

        if not args.quiet:
            console.print(render_kill_report(report))

    if not all_freed:
        sys.exit(1)


def cmd_wait(args):
    """Wait for a port to be freed or opened."""
    try:
        port_num = parse_port(args.port)
    except ValueError as e:
        err_console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    timeout = args.timeout
    interval = args.interval
    target_state = "open" if args.open else "free"
    proto = args.proto

    start_time = time.time()
    console.print(f"[cyan]Waiting for port {port_num} to become {target_state} (timeout: {timeout}s)...[/cyan]")

    while time.time() - start_time < timeout:
        is_free = is_port_free(port_num, proto=proto)
        if args.open:
            # We want it to be occupied/open
            if not is_free:
                elapsed = time.time() - start_time
                console.print(f"[bold green]✓ Port {port_num} is now OPEN ({elapsed:.2f}s elapsed)[/bold green]")
                sys.exit(0)
        else:
            # We want it to be free
            if is_free:
                elapsed = time.time() - start_time
                console.print(f"[bold green]✓ Port {port_num} is now FREE ({elapsed:.2f}s elapsed)[/bold green]")
                sys.exit(0)
        time.sleep(interval)

    err_console.print(f"[bold red]✗ Timed out waiting for port {port_num} to become {target_state}[/bold red]")
    sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="portdock",
        description="⚡ portdock - Interactive Port Conflict Resolver & Ghost Process Dissector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  portdock                  # Launch full interactive TUI dashboard
  portdock 3000             # Dissect / inspect port 3000 in detail
  portdock kill 3000        # Terminate process holding port 3000
  portdock kill 3000 -t     # Ghost killer: purge parent supervisor + worker tree
  portdock kill 3000 8080   # Kill multiple ports in batch
  portdock list --public    # List only ports exposed to 0.0.0.0 / all interfaces
  portdock wait 5432        # Wait until port 5432 is freed
        """,
    )

    parser.add_argument("-v", "--version", action="version", version=f"portdock {__version__}")

    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # list subcommand
    list_p = subparsers.add_parser("list", help="List listening ports")
    list_p.add_argument("--tcp", action="store_true", help="Filter TCP sockets only")
    list_p.add_argument("--udp", action="store_true", help="Filter UDP sockets only")
    list_p.add_argument("--local", action="store_true", help="Filter localhost sockets only (127.0.0.1)")
    list_p.add_argument("--public", action="store_true", help="Filter public sockets only (0.0.0.0)")
    list_p.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # kill subcommand (also aliased by free)
    kill_p = subparsers.add_parser("kill", help="Terminate process(es) holding specified port(s)", aliases=["free"])
    kill_p.add_argument("ports", nargs="+", help="Port number(s) to terminate (e.g. 3000 :8080)")
    kill_p.add_argument("-t", "--tree", action="store_true", help="Ghost killer: terminate parent supervisor and entire process tree")
    kill_p.add_argument("-f", "--force", action="store_true", help="Immediate SIGKILL without graceful SIGTERM wait")
    kill_p.add_argument("-p", "--proto", choices=["tcp", "udp"], default="tcp", help="Protocol (default: tcp)")
    kill_p.add_argument("-q", "--quiet", action="store_true", help="Quiet mode, suppress visual report")

    # wait subcommand
    wait_p = subparsers.add_parser("wait", help="Wait for a port to be freed or opened")
    wait_p.add_argument("port", help="Port number to wait on")
    wait_p.add_argument("--timeout", type=float, default=30.0, help="Maximum seconds to wait (default: 30.0)")
    wait_p.add_argument("--interval", type=float, default=0.1, help="Polling interval in seconds (default: 0.1)")
    wait_p.add_argument("--open", action="store_true", help="Wait until port becomes OPEN instead of free")
    wait_p.add_argument("-p", "--proto", choices=["tcp", "udp"], default="tcp", help="Protocol (default: tcp)")

    # dissect subcommand
    dissect_p = subparsers.add_parser("dissect", help="Deep inspection of a port and its process tree", aliases=["inspect"])
    dissect_p.add_argument("port", help="Port number to dissect")
    dissect_p.add_argument("-p", "--proto", choices=["tcp", "udp"], default="tcp", help="Protocol")

    return parser


def main():
    # If first arg looks like a port number or :port, route directly to dissect
    if len(sys.argv) > 1 and sys.argv[1] not in ("-h", "--help", "-v", "--version", "list", "kill", "free", "wait", "dissect", "inspect"):
        try:
            port_num = parse_port(sys.argv[1])
            cmd_dissect(port_num)
            return
        except ValueError:
            pass

    parser = build_parser()
    args = parser.parse_args()

    if args.subcommand in ("kill", "free"):
        cmd_kill(args)
    elif args.subcommand == "list":
        cmd_list(args)
    elif args.subcommand in ("dissect", "inspect"):
        try:
            port_num = parse_port(args.port)
            cmd_dissect(port_num, proto=args.proto)
        except ValueError as e:
            err_console.print(f"[bold red]Error:[/bold red] {e}")
            sys.exit(1)
    elif args.subcommand == "wait":
        cmd_wait(args)
    else:
        # Default with no args: launch interactive TUI dashboard
        run_interactive_tui()


if __name__ == "__main__":
    main()

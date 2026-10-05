"""
Interactive Rich Terminal TUI and visual formatters for portdock.
"""

from __future__ import annotations
import os
import select
import sys
from typing import List, Optional
from rich import box
from rich.console import Console, Group
from rich.layout import Layout
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .killer import terminate_port
from .models import BindType, KillReport, PortInfo, ProcessTreeNode
from .scanner import get_port_details, scan_listening_ports

console = Console()


def create_ports_table(
    ports: List[PortInfo],
    selected_idx: int = -1,
    filter_query: str = "",
) -> Table:
    """
    Generate a high-density, color-coded Rich table of listening ports.
    """
    table = Table(
        title="",
        expand=True,
        show_header=True,
        header_style="bold cyan",
        box=None,
        padding=(0, 1),
    )

    table.add_column("SEL", justify="center", width=3, no_wrap=True)
    table.add_column("PORT", justify="right", style="bold white", width=11, no_wrap=True)
    table.add_column("BIND", justify="center", width=10, no_wrap=True)
    table.add_column("PID", justify="right", style="cyan", width=8, no_wrap=True)
    table.add_column("PROCESS", style="bold green", width=20, no_wrap=True)
    table.add_column("USER", style="dim", width=12, no_wrap=True)
    table.add_column("MEM", justify="right", width=10, no_wrap=True)
    table.add_column("CPU%", justify="right", width=7, no_wrap=True)
    table.add_column("UPTIME", justify="right", width=10, no_wrap=True)
    table.add_column("COMMAND / CHAIN", style="dim", overflow="ellipsis")

    for idx, p in enumerate(ports):
        is_selected = idx == selected_idx
        sel_marker = "[bold yellow]>[/bold yellow]" if is_selected else " "
        row_style = "reverse" if is_selected else ""

        # Port badge
        port_str = f"[bold cyan]{p.port}[/bold cyan]/{p.proto}"

        # Bind badge
        bind_badge = p.bind_type.badge

        # PID
        pid_str = str(p.pid) if p.pid is not None else "[dim]root[/dim]"

        # Process name with docker container highlight
        proc_str = p.name
        if p.container_name:
            proc_str = f"{p.name} [cyan]({p.container_name[:14]})[/cyan]"

        # Command / supervisor chain
        cmd_or_chain = p.tree_chain if p.tree_chain else p.short_cmdline

        table.add_row(
            sel_marker,
            port_str,
            bind_badge,
            pid_str,
            proc_str,
            p.user or "-",
            p.formatted_memory,
            f"{p.cpu_percent:.1f}%" if p.cpu_percent > 0 else "-",
            p.formatted_uptime,
            cmd_or_chain,
            style=row_style,
        )

    return table


def build_rich_tree(node: ProcessTreeNode, tree: Optional[Tree] = None) -> Tree:
    """
    Recursively build a Rich Tree visual from a ProcessTreeNode.
    """
    label = f"[bold cyan]{node.name}[/bold cyan] [dim](PID: {node.pid})[/dim]"
    if node.memory_mb > 0:
        label += f" [yellow]{node.memory_mb:.1f}MB[/yellow]"
    if node.cmdline:
        short_cmd = node.cmdline[:60] + ("..." if len(node.cmdline) > 60 else "")
        label += f" [dim]-> {short_cmd}[/dim]"

    if tree is None:
        tree = Tree(label)
        root = tree
    else:
        root = tree.add(label)

    for child in node.children:
        build_rich_tree(child, root)

    return tree


def render_port_detail_card(info: PortInfo, interactive: bool = False) -> Panel:
    """
    Render a comprehensive inspector panel for a single port.
    """
    content: List[object] = []

    # Header summary
    header_table = Table.grid(padding=(0, 2))
    header_table.add_column("Field", style="bold dim", width=14)
    header_table.add_column("Value")

    header_table.add_row("Port / Proto", f"[bold cyan]{info.port}[/bold cyan] ({info.proto.upper()})")
    header_table.add_row("Bind Address", f"{info.bind_ip} -> {info.bind_type.badge_full}")
    header_table.add_row("PID", f"[bold yellow]{info.pid}[/bold yellow]" if info.pid else "[bold red]Protected / Root[/bold red]")
    header_table.add_row("Process Name", f"[bold green]{info.name}[/bold green]")
    header_table.add_row("User", info.user or "Unknown")
    header_table.add_row("Memory RSS", info.formatted_memory)
    header_table.add_row("CPU Usage", f"{info.cpu_percent:.1f}%")
    header_table.add_row("Uptime", info.formatted_uptime)
    if info.cwd:
        header_table.add_row("Working Dir", f"[blue]{info.cwd}[/blue]")

    content.append(header_table)

    if info.container_name:
        content.append(Text("\n[Docker Container]", style="bold magenta"))
        content.append(Text(f"  Container: {info.container_name}", style="cyan"))

    if info.cmdline:
        content.append(Text("\n[Full Command Line]", style="bold magenta"))
        content.append(Padding(Text(info.cmdline, style="white"), (0, 2)))

    if info.tree_chain:
        content.append(Text("\n[Supervisor Hierarchy]", style="bold magenta"))
        content.append(Text(f"  {info.tree_chain}", style="yellow"))

    if info.process_tree and info.process_tree.children:
        content.append(Text("\n[Process Tree (Workers & Subprocesses)]", style="bold magenta"))
        content.append(build_rich_tree(info.process_tree))

    # Actionable guidance
    content.append(Text("\n[Available Actions]", style="bold dim"))
    actions_text = Text()
    actions_text.append(f"  portdock kill {info.port}     ", style="bold white")
    actions_text.append("-> Standard kill (graceful SIGTERM -> SIGKILL)\n", style="dim")
    actions_text.append(f"  portdock kill {info.port} -t  ", style="bold white")
    actions_text.append("-> Tree kill (terminates parent supervisor + workers)\n", style="dim")
    actions_text.append(f"  portdock kill {info.port} -f  ", style="bold white")
    actions_text.append("-> Force kill (immediate SIGKILL)\n", style="dim")
    content.append(actions_text)

    subtitle = "[dim]Press \\[k] Kill | \\[t] Tree Kill | \\[q] or \\[Enter] Back[/dim]" if interactive else None

    return Panel(
        Group(*content),
        title=f"[bold cyan]Port Inspector: :{info.port}[/bold cyan]",
        subtitle=subtitle,
        border_style="cyan",
        padding=(1, 2),
    )


def render_kill_report(report: KillReport) -> Panel:
    """
    Render a clean status report after a kill operation.
    """
    content: List[object] = []

    if report.freed:
        if not report.pids_killed and not report.pids_targeted:
            status_text = Text(f"PORT {report.port} IS ALREADY FREE (No active listening processes)", style="bold green")
        else:
            status_text = Text(f"PORT {report.port} SUCCESSFULLY FREED", style="bold green")
    else:
        status_text = Text(f"PORT {report.port} STILL BUSY", style="bold red")

    content.append(status_text)

    if report.killed_process_names:
        content.append(Text(f"\nTerminated processes ({len(report.killed_process_names)}):", style="bold white"))
        for name in report.killed_process_names:
            content.append(Text(f"  - {name}", style="cyan"))

    if report.tree_killed:
        content.append(Text("\nMode: Full Process Tree & Supervisor Purged (-t)", style="yellow"))

    if report.error_message:
        content.append(Text(f"\nWarning: {report.error_message}", style="bold red"))

    border_color = "green" if report.freed else "red"
    return Panel(
        Group(*content),
        title="[bold]portdock kill report[/bold]",
        border_style=border_color,
        padding=(1, 2),
    )


def _read_key() -> str:
    """
    Read a single keypress in raw terminal mode on Linux/macOS.
    """
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if not ch or ch == "\x04":  # EOF or Ctrl+D
            return "q"
        if ch == "\x1b":
            # Check for escape sequences
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A":
                        return "UP"
                    elif ch3 == "B":
                        return "DOWN"
                    elif ch3 == "C":
                        return "RIGHT"
                    elif ch3 == "D":
                        return "LEFT"
            return "ESC"
        elif ch in ("\r", "\n"):
            return "ENTER"
        elif ch == "\x03":  # Ctrl+C
            return "CTRL_C"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def run_interactive_tui(proto_filter: Optional[str] = None):
    """
    Run the full-screen interactive TUI dashboard.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        # Fallback to static table if not interactive TTY
        ports = scan_listening_ports(proto_filter=proto_filter)
        tbl = create_ports_table(ports)
        console.print(tbl)
        return

    from rich.live import Live

    filter_query = ""
    selected_idx = 0
    status_msg = ""
    inspect_port: Optional[int] = None

    while True:
        # Load fresh ports
        all_ports = scan_listening_ports(proto_filter=proto_filter)
        if filter_query:
            q = filter_query.lower()
            filtered_ports = [
                p
                for p in all_ports
                if q in str(p.port)
                or q in p.name.lower()
                or q in p.bind_ip.lower()
                or q in (p.user or "").lower()
                or q in (p.container_name or "").lower()
            ]
        else:
            filtered_ports = all_ports

        # Clamp selection index
        if filtered_ports:
            selected_idx = max(0, min(selected_idx, len(filtered_ports) - 1))
        else:
            selected_idx = 0

        # Build UI layout
        header_text = Text()
        header_text.append("⚡ PORTDOCK ", style="bold cyan")
        header_text.append(f"| Active: {len(all_ports)} ", style="bold white")
        local_count = sum(1 for p in all_ports if p.bind_type == BindType.LOCAL)
        pub_count = sum(1 for p in all_ports if p.bind_type == BindType.PUBLIC)
        header_text.append(f"| Local: [green]{local_count}[/green] ", style="white")
        header_text.append(f"| Public: [bold red]{pub_count}[/bold red] ", style="white")
        if filter_query:
            header_text.append(f"| Filter: '{filter_query}' ", style="bold yellow")

        # Shortcuts footer
        footer_text = Text()
        footer_text.append("[↑/↓/j/k] Navigate  ", style="cyan")
        footer_text.append("[Enter/d] Inspect  ", style="cyan")
        footer_text.append("[k] Kill  ", style="bold red")
        footer_text.append("[t] Tree Kill  ", style="bold yellow")
        footer_text.append("[f] Filter  ", style="cyan")
        footer_text.append("[r] Refresh  ", style="cyan")
        footer_text.append("[q] Quit", style="white")

        if inspect_port is not None:
            details = get_port_details(inspect_port)
            if details:
                main_renderable = render_port_detail_card(details, interactive=True)
            else:
                main_renderable = Panel(Text(f"Port {inspect_port} is no longer active.", style="red"))
        else:
            table = create_ports_table(
                filtered_ports,
                selected_idx=selected_idx,
                filter_query=filter_query,
            )
            main_renderable = table

        # Render screen
        console.clear()
        console.print(Panel(header_text, style="cyan", box=box.ROUNDED))
        if status_msg:
            console.print(f" {status_msg}\n")
        console.print(main_renderable)
        console.print(Panel(footer_text, style="dim", box=box.ROUNDED))

        # Wait for key
        key = _read_key()

        if key in ("q", "ESC", "CTRL_C"):
            if inspect_port is not None:
                inspect_port = None
                status_msg = ""
                continue
            else:
                break

        if inspect_port is not None:
            if key in ("ENTER", "d"):
                inspect_port = None
                status_msg = ""
            elif key == "k":
                report = terminate_port(inspect_port, force=False, kill_tree=False)
                if report.freed:
                    status_msg = f"[bold green]Killed port {inspect_port}[/bold green]"
                else:
                    status_msg = f"[bold red]Failed to free port {inspect_port}: {report.error_message}[/bold red]"
                inspect_port = None
            elif key == "t":
                report = terminate_port(inspect_port, force=False, kill_tree=True)
                if report.freed:
                    status_msg = f"[bold green]Tree killed port {inspect_port} (purged {len(report.killed_pids)} processes)[/bold green]"
                else:
                    status_msg = f"[bold red]Tree kill failed for port {inspect_port}: {report.error_message}[/bold red]"
                inspect_port = None
            continue

        if key in ("UP", "k"):
            selected_idx = max(0, selected_idx - 1)
            status_msg = ""
        elif key in ("DOWN", "j"):
            if filtered_ports:
                selected_idx = min(len(filtered_ports) - 1, selected_idx + 1)
            status_msg = ""
        elif key in ("ENTER", "d"):
            if filtered_ports:
                inspect_port = filtered_ports[selected_idx].port
                status_msg = ""
        elif key == "r":
            status_msg = "[green]Refreshed.[/green]"
        elif key == "f":
            # Prompt for filter
            console.print("\n[bold yellow]Enter filter query (press Enter to apply, empty to clear):[/bold yellow]")
            try:
                filter_query = input("> ").strip()
                status_msg = f"Filter set to: '{filter_query}'" if filter_query else "Filter cleared."
            except (EOFError, KeyboardInterrupt):
                pass
        elif key == "k":
            # Quick Kill
            if filtered_ports:
                target = filtered_ports[selected_idx]
                report = terminate_port(target.port, force=False, kill_tree=False)
                if report.freed:
                    status_msg = f"[bold green]Killed port {target.port} ({target.name})[/bold green]"
                else:
                    status_msg = f"[bold red]Failed to free port {target.port}: {report.error_message}[/bold red]"
        elif key == "t":
            # Tree Kill
            if filtered_ports:
                target = filtered_ports[selected_idx]
                report = terminate_port(target.port, force=False, kill_tree=True)
                if report.freed:
                    status_msg = f"[bold green]Tree killed port {target.port} (purged {len(report.killed_pids)} processes)[/bold green]"
                else:
                    status_msg = f"[bold red]Tree kill failed for port {target.port}: {report.error_message}[/bold red]"

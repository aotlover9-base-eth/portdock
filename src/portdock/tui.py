"""
Interactive Rich Terminal TUI and visual formatters for portdock.
"""

from __future__ import annotations
import os
import select
import shutil
import sys
from typing import List, Optional, Tuple
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

    subtitle = "[dim]Press [k] Kill | [t] Tree Kill | [Esc / Enter] Back[/dim]" if interactive else None

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
    Handles arrow keys, function keys, backspace, esc, enter, tab, and printable characters.
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
                    elif ch3 == "H":
                        return "HOME"
                    elif ch3 == "F":
                        return "END"
                    elif ch3 in ("1", "4", "5", "6"):
                        # Read trailing ~
                        r2, _, _ = select.select([sys.stdin], [], [], 0.02)
                        if r2:
                            sys.stdin.read(1)
                        if ch3 == "5":
                            return "PAGE_UP"
                        elif ch3 == "6":
                            return "PAGE_DOWN"
                        elif ch3 == "1":
                            return "HOME"
                        elif ch3 == "4":
                            return "END"
            return "ESC"
        elif ch in ("\r", "\n"):
            return "ENTER"
        elif ch == "\t":
            return "TAB"
        elif ch in ("\x7f", "\x08"):
            return "BACKSPACE"
        elif ch == " ":
            return "SPACE"
        elif ch == "\x03":  # Ctrl+C
            return "CTRL_C"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def run_interactive_tui(proto_filter: Optional[str] = None):
    """
    Run the full-screen interactive TUI dashboard with zero-flicker rendering,
    intuitive controls, Dev/System socket toggle, and interactive search.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        # Fallback to static table if not interactive TTY
        ports = scan_listening_ports(proto_filter=proto_filter)
        tbl = create_ports_table(ports)
        console.print(tbl)
        return

    filter_query = ""
    is_searching = False
    search_buffer = ""
    show_system = False
    selected_idx = 0
    scroll_offset = 0
    status_msg = ""
    inspect_port: Optional[int] = None
    confirm_state: Optional[dict] = None

    # Switch to alternate screen buffer and hide cursor
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    sys.stdout.flush()

    try:
        while True:
            # 1. Fetch current listening ports
            all_ports = scan_listening_ports(proto_filter=proto_filter)

            # Categorize
            system_count = sum(1 for p in all_ports if p.is_system)
            dev_ports = [p for p in all_ports if not p.is_system]
            base_ports = all_ports if show_system else dev_ports

            # Apply search filter
            if filter_query:
                q = filter_query.lower()
                active_ports = [
                    p
                    for p in all_ports
                    if q in str(p.port)
                    or q in p.name.lower()
                    or q in p.bind_ip.lower()
                    or q in (p.user or "").lower()
                    or q in (p.container_name or "").lower()
                    or q in p.cmdline.lower()
                ]
            else:
                active_ports = base_ports

            # Clamp selection
            if active_ports:
                selected_idx = max(0, min(selected_idx, len(active_ports) - 1))
            else:
                selected_idx = 0

            # 2. Window viewport calculation
            term_size = shutil.get_terminal_size()
            term_height = term_size.lines
            term_width = term_size.columns

            # Overhead lines: Header(3) + Banner(2-3) + Table Header(2) + Footer(3) + Margins(2) ~= 12
            visible_rows = max(4, term_height - 12)

            if selected_idx < scroll_offset:
                scroll_offset = selected_idx
            elif selected_idx >= scroll_offset + visible_rows:
                scroll_offset = selected_idx - visible_rows + 1

            max_offset = max(0, len(active_ports) - visible_rows)
            scroll_offset = max(0, min(scroll_offset, max_offset))

            windowed_ports = active_ports[scroll_offset : scroll_offset + visible_rows]

            # 3. Build UI Components
            local_count = sum(1 for p in all_ports if p.bind_type == BindType.LOCAL)
            pub_count = sum(1 for p in all_ports if p.bind_type == BindType.PUBLIC)

            header_text = Text()
            header_text.append("PORTDOCK ", style="bold cyan")
            header_text.append(f"• Total: {len(all_ports)} ", style="bold white")
            header_text.append("• Local: ", style="white")
            header_text.append(f"{local_count} ", style="bold green")
            header_text.append("• Public: ", style="white")
            header_text.append(f"{pub_count} ", style="bold red")

            if filter_query:
                header_text.append("• Filter: ", style="white")
                header_text.append(f"'{filter_query}' ({len(active_ports)} matches) ", style="bold yellow")
            elif not show_system:
                header_text.append("• View: ", style="white")
                header_text.append("Dev Apps Only ", style="bold green")
                header_text.append(f"({system_count} system sockets hidden, [Tab] for All) ", style="dim")
            else:
                header_text.append("• View: ", style="white")
                header_text.append("All Ports ", style="bold magenta")
                header_text.append(f"([Tab] for Dev Apps) ", style="dim")

            header_panel = Panel(header_text, style="cyan", box=box.ROUNDED)

            # Banner / Confirmation / Search Bar
            banner = None
            if confirm_state is not None:
                act = confirm_state["action"]
                c_port = confirm_state["port"]
                c_name = confirm_state["name"]
                c_pid = confirm_state["pid"]
                if act == "kill":
                    t = Text()
                    t.append(f"[!] KILL PROCESS ON PORT :{c_port}?\n", style="bold red")
                    t.append(f"    Process: {c_name} (PID: {c_pid or 'root'})\n", style="bold cyan")
                    t.append("    [Enter] Confirm Kill    [Esc / q] Cancel", style="bold green")
                    banner = Panel(t, border_style="red", box=box.ROUNDED)
                else:
                    t = Text()
                    t.append(f"[TREE] PURGE PROCESS TREE ON PORT :{c_port}?\n", style="bold yellow")
                    t.append(f"    Terminates '{c_name}' and all parent supervisors/child workers.\n", style="bold cyan")
                    t.append("    [Enter] Confirm Tree Kill    [Esc / q] Cancel", style="bold green")
                    banner = Panel(t, border_style="yellow", box=box.ROUNDED)
            elif is_searching:
                t = Text()
                t.append("Search / Filter: ", style="bold white")
                t.append(f"{search_buffer}█  ", style="bold cyan")
                t.append("([Type] Search • [Enter] Keep • [Esc] Clear & Exit)", style="dim")
                banner = Panel(t, border_style="cyan", box=box.ROUNDED)
            elif status_msg:
                banner_style = "bold green" if ("freed" in status_msg or "Tree killed" in status_msg) else ("bold red" if "Failed" in status_msg else "cyan")
                banner = Text(f"  {status_msg}", style=banner_style)

            # Main content: Inspector vs Table
            scroll_indicator = None
            if inspect_port is not None:
                details = get_port_details(inspect_port)
                if details:
                    main_renderable = render_port_detail_card(details, interactive=True)
                else:
                    main_renderable = Panel(Text(f"Port {inspect_port} is no longer active.", style="red"))
            else:
                if not active_ports:
                    main_renderable = Panel(
                        Text("No active listening ports match current view / filter.\nPress [Tab] to show system sockets or [/] to adjust search.", style="dim italic"),
                        border_style="dim",
                    )
                else:
                    selected_in_window = selected_idx - scroll_offset
                    table = create_ports_table(
                        windowed_ports,
                        selected_idx=selected_in_window,
                        filter_query=filter_query,
                    )
                    main_renderable = table

                    # Scroll indicators
                    scroll_parts = []
                    if scroll_offset > 0:
                        scroll_parts.append(f"▲ {scroll_offset} more above")
                    if scroll_offset + len(windowed_ports) < len(active_ports):
                        scroll_parts.append(f"▼ {len(active_ports) - (scroll_offset + len(windowed_ports))} more below")
                    if scroll_parts:
                        scroll_indicator = Text("  " + "  •  ".join(scroll_parts), style="dim italic")

            # Footer
            if inspect_port is not None:
                footer_text = Text()
                footer_text.append("[k] ", style="bold white")
                footer_text.append("Kill Port  •  ", style="white")
                footer_text.append("[t] ", style="bold yellow")
                footer_text.append("Tree Kill  •  ", style="white")
                footer_text.append("[Esc / Enter] ", style="bold cyan")
                footer_text.append("Back to Dashboard", style="white")
            elif is_searching:
                footer_text = Text()
                footer_text.append("[Type] ", style="bold cyan")
                footer_text.append("Filter  •  ", style="white")
                footer_text.append("[Enter] ", style="bold green")
                footer_text.append("Done  •  ", style="white")
                footer_text.append("[Esc] ", style="bold dim")
                footer_text.append("Clear  •  ", style="white")
                footer_text.append("[↑/↓] ", style="bold cyan")
                footer_text.append("Navigate", style="white")
            elif confirm_state is not None:
                footer_text = Text()
                footer_text.append("[Enter] ", style="bold green")
                footer_text.append("Confirm Action  •  ", style="white")
                footer_text.append("[Esc / q] ", style="bold dim")
                footer_text.append("Cancel", style="white")
            else:
                footer_text = Text()
                footer_text.append("[↑/↓ or j/k] ", style="bold cyan")
                footer_text.append("Move  •  ", style="white")
                footer_text.append("[Enter] ", style="bold cyan")
                footer_text.append("Inspect  •  ", style="white")
                footer_text.append("[k] ", style="bold red")
                footer_text.append("Kill  •  ", style="white")
                footer_text.append("[t] ", style="bold yellow")
                footer_text.append("Tree Kill  •  ", style="white")
                footer_text.append("[Tab] ", style="bold magenta")
                footer_text.append("Dev/All  •  ", style="white")
                footer_text.append("[/] ", style="bold cyan")
                footer_text.append("Search  •  ", style="white")
                footer_text.append("[r] ", style="bold white")
                footer_text.append("Refresh  •  ", style="white")
                footer_text.append("[q] ", style="bold white")
                footer_text.append("Quit", style="white")

            footer_panel = Panel(footer_text, style="dim", box=box.ROUNDED)

            # 4. Render entire frame into buffer and overwrite screen in 1 atomic draw (zero flicker!)
            render_console = Console(width=term_width, color_system=console.color_system)
            with render_console.capture() as capture:
                render_console.print(header_panel)
                if banner is not None:
                    render_console.print(banner)
                render_console.print(main_renderable)
                if scroll_indicator is not None:
                    render_console.print(scroll_indicator)
                render_console.print(footer_panel)

            frame = capture.get()
            sys.stdout.write("\x1b[H" + frame + "\x1b[J")
            sys.stdout.flush()

            # 5. Read Key Input
            key = _read_key()

            # Handle Confirmation State
            if confirm_state is not None:
                if key == "ENTER":
                    target_port = confirm_state["port"]
                    act = confirm_state["action"]
                    is_tree = (act == "tree_kill")
                    report = terminate_port(target_port, force=False, kill_tree=is_tree)
                    if report.freed:
                        if is_tree:
                            status_msg = f"Tree killed port :{target_port} (purged {len(report.killed_pids)} processes)"
                        else:
                            status_msg = f"Successfully freed port :{target_port}"
                    else:
                        status_msg = f"Failed to free port :{target_port}: {report.error_message}"
                    confirm_state = None
                    inspect_port = None
                elif key in ("ESC", "q", "n", "CTRL_C"):
                    confirm_state = None
                    status_msg = "Cancelled."
                continue

            # Handle Search Mode Input
            if is_searching:
                if key == "ENTER":
                    filter_query = search_buffer
                    is_searching = False
                    status_msg = f"Filtered by '{filter_query}'" if filter_query else ""
                elif key == "ESC":
                    filter_query = ""
                    search_buffer = ""
                    is_searching = False
                    status_msg = "Filter cleared."
                elif key == "BACKSPACE":
                    search_buffer = search_buffer[:-1]
                    filter_query = search_buffer
                    selected_idx = 0
                elif key in ("UP",):
                    selected_idx = max(0, selected_idx - 1)
                elif key in ("DOWN",):
                    if active_ports:
                        selected_idx = min(len(active_ports) - 1, selected_idx + 1)
                elif key == "CTRL_C":
                    break
                elif len(key) == 1 and key.isprintable():
                    search_buffer += key
                    filter_query = search_buffer
                    selected_idx = 0
                continue

            # Handle Inspector Mode Input
            if inspect_port is not None:
                if key in ("q", "ESC", "ENTER", "d"):
                    inspect_port = None
                    status_msg = ""
                elif key == "k":
                    target_info = get_port_details(inspect_port)
                    if target_info:
                        confirm_state = {"action": "kill", "port": target_info.port, "name": target_info.name, "pid": target_info.pid}
                    else:
                        status_msg = f"Port :{inspect_port} is no longer active."
                        inspect_port = None
                elif key == "t":
                    target_info = get_port_details(inspect_port)
                    if target_info:
                        confirm_state = {"action": "tree_kill", "port": target_info.port, "name": target_info.name, "pid": target_info.pid}
                    else:
                        status_msg = f"Port :{inspect_port} is no longer active."
                        inspect_port = None
                continue

            # Normal List Navigation
            if key in ("q", "CTRL_C"):
                break
            elif key in ("UP", "k"):
                selected_idx = max(0, selected_idx - 1)
                status_msg = ""
            elif key in ("DOWN", "j"):
                if active_ports:
                    selected_idx = min(len(active_ports) - 1, selected_idx + 1)
                status_msg = ""
            elif key in ("PAGE_UP", "b"):
                selected_idx = max(0, selected_idx - visible_rows)
                status_msg = ""
            elif key in ("PAGE_DOWN", "SPACE"):
                if active_ports:
                    selected_idx = min(len(active_ports) - 1, selected_idx + visible_rows)
                status_msg = ""
            elif key == "HOME":
                selected_idx = 0
                status_msg = ""
            elif key == "END":
                if active_ports:
                    selected_idx = len(active_ports) - 1
                status_msg = ""
            elif key == "TAB":
                show_system = not show_system
                selected_idx = 0
                scroll_offset = 0
                status_msg = "Showing all system ports" if show_system else "Showing developer apps only"
            elif key in ("/", "f"):
                is_searching = True
                search_buffer = filter_query
            elif key in ("ENTER", "d", "i"):
                if active_ports:
                    inspect_port = active_ports[selected_idx].port
                    status_msg = ""
            elif key == "k":
                if active_ports:
                    target = active_ports[selected_idx]
                    confirm_state = {"action": "kill", "port": target.port, "name": target.name, "pid": target.pid}
            elif key == "t":
                if active_ports:
                    target = active_ports[selected_idx]
                    confirm_state = {"action": "tree_kill", "port": target.port, "name": target.name, "pid": target.pid}
            elif key == "r":
                status_msg = "Refreshed."

    finally:
        # Restore normal terminal screen buffer and show cursor
        sys.stdout.write("\x1b[?1049l\x1b[?25h")
        sys.stdout.flush()

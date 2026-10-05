import pytest
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from portdock.models import BindType, KillReport, PortInfo, ProcessTreeNode
from portdock.tui import (
    build_rich_tree,
    create_ports_table,
    render_kill_report,
    render_port_detail_card,
)


@pytest.fixture
def sample_ports():
    p1 = PortInfo(
        port=3000,
        proto="tcp",
        bind_ip="127.0.0.1",
        bind_type=BindType.LOCAL,
        pid=1234,
        name="node",
        user="devuser",
        memory_mb=64.0,
        cpu_percent=0.5,
    )
    p2 = PortInfo(
        port=8080,
        proto="tcp",
        bind_ip="0.0.0.0",
        bind_type=BindType.PUBLIC,
        pid=5678,
        name="docker-proxy",
        user="root",
        container_name="web-service",
    )
    return [p1, p2]


def test_create_ports_table(sample_ports):
    table = create_ports_table(sample_ports, selected_idx=0)
    assert isinstance(table, Table)
    assert len(table.rows) == 2


def test_build_rich_tree():
    root = ProcessTreeNode(
        pid=1000,
        name="pm2",
        cmdline="pm2 God Daemon",
        children=[
            ProcessTreeNode(pid=1001, name="node-app", cmdline="node server.js", memory_mb=45.0)
        ],
    )
    tree = build_rich_tree(root)
    assert isinstance(tree, Tree)


def test_render_port_detail_card(sample_ports):
    card = render_port_detail_card(sample_ports[0], interactive=True)
    assert isinstance(card, Panel)
    assert "3000" in card.title


def test_render_kill_report():
    report = KillReport(
        port=3000,
        pids_targeted=[1234],
        pids_killed=[1234],
        killed_process_names=["node"],
        success=True,
        freed=True,
    )
    panel = render_kill_report(report)
    assert isinstance(panel, Panel)

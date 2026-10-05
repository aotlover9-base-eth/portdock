import time
from portdock.models import BindType, KillReport, PortInfo, ProcessTreeNode, detect_bind_type


def test_detect_bind_type():
    assert detect_bind_type("127.0.0.1") == BindType.LOCAL
    assert detect_bind_type("::1") == BindType.LOCAL
    assert detect_bind_type("localhost") == BindType.LOCAL

    assert detect_bind_type("0.0.0.0") == BindType.PUBLIC
    assert detect_bind_type("::") == BindType.PUBLIC
    assert detect_bind_type("*") == BindType.PUBLIC
    assert detect_bind_type("") == BindType.PUBLIC

    assert detect_bind_type("192.168.1.10") == BindType.SPECIFIC
    assert detect_bind_type("10.0.0.1") == BindType.SPECIFIC


def test_bind_type_badges():
    assert "LOCAL" in BindType.LOCAL.badge
    assert "PUBLIC" in BindType.PUBLIC.badge
    assert "SPECIFIC" in BindType.SPECIFIC.badge

    assert "Localhost" in BindType.LOCAL.badge_full
    assert "Public" in BindType.PUBLIC.badge_full


def test_port_info_formatting():
    info = PortInfo(
        port=3000,
        proto="tcp",
        bind_ip="127.0.0.1",
        bind_type=BindType.LOCAL,
        pid=1234,
        name="node",
        memory_mb=128.5,
        cpu_percent=1.5,
        created_time=time.time() - 3665,  # ~1h 1m
        cmdline="/usr/local/bin/node /app/server.js --port 3000",
    )

    assert info.display_name == "node"
    assert info.formatted_memory == "128.5 MB"
    assert "1h 01m" in info.formatted_uptime
    assert "node" in info.short_cmdline


def test_port_info_container_name():
    info = PortInfo(
        port=5432,
        proto="tcp",
        bind_ip="0.0.0.0",
        bind_type=BindType.PUBLIC,
        name="docker-proxy",
        container_name="db-postgres (postgres:15)",
    )
    assert "[db-postgres (postgres:15)]" in info.display_name


def test_kill_report():
    report = KillReport(
        port=8080,
        pids_targeted=[100, 101],
        pids_killed=[100, 101],
        killed_process_names=["supervisor", "worker"],
        tree_killed=True,
        success=True,
        freed=True,
    )
    assert report.port == 8080
    assert report.freed is True
    assert len(report.pids_killed) == 2
    assert report.tree_killed is True

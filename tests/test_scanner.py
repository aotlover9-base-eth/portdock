import socket
import psutil
from portdock.scanner import (
    get_port_details,
    is_port_free,
    is_shell_or_init,
    scan_listening_ports,
)


def test_is_shell_or_init():
    assert is_shell_or_init("bash") is True
    assert is_shell_or_init("zsh") is True
    assert is_shell_or_init("systemd") is True
    assert is_shell_or_init("gnome-terminal") is True
    assert is_shell_or_init("init") is True

    assert is_shell_or_init("node") is False
    assert is_shell_or_init("python3") is False
    assert is_shell_or_init("vite") is False
    assert is_shell_or_init("cargo") is False


def test_is_port_free_and_scan():
    # Find an ephemeral free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)

        # Port should not be free while listening
        assert is_port_free(port) is False

        # Should be visible in scan_listening_ports
        ports = scan_listening_ports(proto_filter="tcp")
        matching = [p for p in ports if p.port == port]
        assert len(matching) >= 1
        assert matching[0].proto == "tcp"

        # Details check
        details = get_port_details(port, proto="tcp")
        assert details is not None
        assert details.port == port
        assert details.pid == psutil.Process().pid

    # Once closed, port should be free
    assert is_port_free(port) is True

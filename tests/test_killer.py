import os
import subprocess
import sys
import time
from portdock.killer import terminate_port
from portdock.scanner import is_port_free


def test_terminate_already_free_port():
    # Pick a high port unlikely to be open
    report = terminate_port(59998)
    assert report.freed is True
    assert report.success is True
    assert len(report.pids_killed) == 0


def test_terminate_active_port():
    code = """
import socket, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', 59140))
s.listen(1)
while True:
    time.sleep(0.1)
"""
    p = subprocess.Popen([sys.executable, "-c", code])
    try:
        # Wait until port is occupied
        for _ in range(50):
            if not is_port_free(59140):
                break
            time.sleep(0.05)

        assert not is_port_free(59140)

        # Terminate port
        report = terminate_port(59140, force=False)
        assert report.freed is True
        assert report.success is True
        assert p.pid in report.pids_killed
        assert is_port_free(59140) is True
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_terminate_tree():
    # Supervisor spawns worker which binds port
    sup_code = """
import subprocess, sys, time
worker_code = '''
import socket, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', 59141))
s.listen(1)
while True:
    time.sleep(0.1)
'''
worker = subprocess.Popen([sys.executable, '-c', worker_code])
while True:
    time.sleep(0.2)
"""
    sup = subprocess.Popen([sys.executable, "-c", sup_code])
    try:
        # Wait until port is occupied
        for _ in range(50):
            if not is_port_free(59141):
                break
            time.sleep(0.05)

        assert not is_port_free(59141)

        # Terminate with tree=True
        report = terminate_port(59141, kill_tree=True)
        assert report.freed is True
        assert report.tree_killed is True
        assert len(report.pids_killed) >= 2
        assert sup.pid in report.pids_killed

        # Verify supervisor process is dead
        time.sleep(0.1)
        assert sup.poll() is not None
        assert is_port_free(59141) is True
    finally:
        if sup.poll() is None:
            sup.kill()
            sup.wait()

import argparse
import json
import sys
import pytest
from portdock.cli import build_parser, cmd_dissect, cmd_kill, cmd_list, cmd_wait, main, parse_port


def test_parse_port():
    assert parse_port("80") == 80
    assert parse_port(":8080") == 8080
    assert parse_port("localhost:3000") == 3000
    assert parse_port("http://localhost:5000") == 5000
    assert parse_port("5000/tcp") == 5000
    assert parse_port("http://localhost:3000?foo=bar") == 3000
    assert parse_port("http://localhost:3000#section") == 3000
    assert parse_port("http://localhost:3000/api/test?foo=1#hash") == 3000
    assert parse_port("[::1]:9090") == 9090
    assert parse_port("https://sub.example.com:8443/v2/items?id=10#tab") == 8443

    with pytest.raises(ValueError):
        parse_port("invalid")

    with pytest.raises(ValueError):
        parse_port("0")

    with pytest.raises(ValueError):
        parse_port("70000")

    with pytest.raises(ValueError):
        parse_port("-80")


def test_build_parser():
    parser = build_parser()
    args = parser.parse_args(["kill", "3000", "-t"])
    assert args.subcommand == "kill"
    assert args.ports == ["3000"]
    assert args.tree is True

    # Test free alias
    args_free = parser.parse_args(["free", "4000", "-f"])
    assert args_free.subcommand == "free"
    assert args_free.ports == ["4000"]
    assert args_free.force is True

    args2 = parser.parse_args(["list", "--public", "--json"])
    assert args2.subcommand == "list"
    assert args2.public is True
    assert args2.json is True

    args3 = parser.parse_args(["wait", "8080", "--open", "--timeout", "10"])
    assert args3.subcommand == "wait"
    assert args3.port == "8080"
    assert args3.open is True
    assert args3.timeout == 10.0


def test_cmd_list_json(capsys):
    parser = build_parser()
    args = parser.parse_args(["list", "--json"])
    cmd_list(args)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    if data:
        item = data[0]
        assert "port" in item
        assert "proto" in item
        assert "bind_type" in item


def test_cmd_list_filters(capsys):
    parser = build_parser()
    args_local = parser.parse_args(["list", "--local"])
    cmd_list(args_local)
    captured = capsys.readouterr()
    assert "PORTDOCK" in captured.out

    args_public = parser.parse_args(["list", "--public"])
    cmd_list(args_public)
    captured = capsys.readouterr()
    assert "PORTDOCK" in captured.out


def test_cmd_dissect_free_port(capsys):
    cmd_dissect(59991)
    captured = capsys.readouterr()
    assert "FREE" in captured.out


def test_cmd_kill_already_free(capsys):
    parser = build_parser()
    args = parser.parse_args(["kill", "59992", "59993"])
    cmd_kill(args)
    captured = capsys.readouterr()
    assert "ALREADY FREE" in captured.out


def test_direct_port_args(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["portdock", ":59995"])
    main()
    captured = capsys.readouterr()
    assert "FREE" in captured.out

    monkeypatch.setattr(sys, "argv", ["portdock", "localhost:59995"])
    main()
    captured = capsys.readouterr()
    assert "FREE" in captured.out


def test_cmd_wait_timeout(capsys):
    parser = build_parser()
    args = parser.parse_args(["wait", "59997", "--open", "--timeout", "0.05", "--interval", "0.01"])
    with pytest.raises(SystemExit) as exc_info:
        cmd_wait(args)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Timed out" in captured.err


def test_cmd_kill_invalid_port(capsys):
    parser = build_parser()
    args = parser.parse_args(["kill", "not_a_port"])
    with pytest.raises(SystemExit) as exc_info:
        cmd_kill(args)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_cmd_wait_invalid_port(capsys):
    parser = build_parser()
    args = parser.parse_args(["wait", "not_a_port"])
    with pytest.raises(SystemExit) as exc_info:
        cmd_wait(args)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err

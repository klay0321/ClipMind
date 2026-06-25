"""scripts/diagnose_ai_network.py 纯函数 + 退出码单元测试（CI 无需真实网络/Provider）。

覆盖：脱敏、地址分类、dotenv 优先级（系统环境 > .env）、引号解析、空 URL 安全失败、
不输出 Key、子网重叠检测（IPv4/IPv6/多地址/非法 CIDR）、--fail-on-overlap 退出码。
全部使用通用示例域名/地址，绝不含真实 Endpoint。
"""

from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "diagnose_ai_network.py"
_spec = importlib.util.spec_from_file_location("diagnose_ai_network", _SCRIPT)
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)


# ---- 脱敏 / 分类 ----

def test_redact_host_masks_first_label():
    out = diag._redact_host("inference-cn.example-llm.test")  # 通用示例
    assert "example-llm.test" in out
    assert "inference-cn" not in out
    assert out.startswith("i") and "***" in out


def test_redact_host_short_and_empty():
    assert diag._redact_host("") == "(empty)"
    assert diag._redact_host("ab") == "***"


def test_addr_type_classifies():
    assert diag._addr_type("172.20.30.40") == "private"
    assert diag._addr_type("10.0.0.5") == "private"
    assert diag._addr_type("127.0.0.1") == "loopback"
    assert diag._addr_type("8.8.8.8") == "public"
    assert diag._addr_type("not-an-ip") == "invalid"


# ---- dotenv 优先级：系统环境 > .env > 默认 ----

def test_dotenv_loads_when_absent(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("AI_BASE_URL=https://example.test/v1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    diag._load_dotenv(".env")
    assert os.environ["AI_BASE_URL"] == "https://example.test/v1"


def test_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("AI_BASE_URL=https://from-dotenv.test/v1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_BASE_URL", "https://from-env.test/v1")  # 已注入，优先
    diag._load_dotenv(".env")
    assert os.environ["AI_BASE_URL"] == "https://from-env.test/v1"  # .env 不覆盖


def test_dotenv_double_quotes(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('AI_BASE_URL="https://example.test/v1"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    diag._load_dotenv(".env")
    assert os.environ["AI_BASE_URL"] == "https://example.test/v1"


def test_dotenv_single_quotes_and_in_file_last_wins(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "AI_BASE_URL=\nAI_BASE_URL='https://example.test/v1'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    diag._load_dotenv(".env")
    assert os.environ["AI_BASE_URL"] == "https://example.test/v1"  # 单引号去除 + 文件内 last-wins


# ---- 空 URL 安全失败 ----

def test_main_returns_3_on_empty_base(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["diagnose_ai_network.py"])
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    assert diag.main() == 3


def test_main_returns_3_on_empty_host(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["diagnose_ai_network.py"])
    monkeypatch.setenv("AI_BASE_URL", "https:///v1")  # 非空但无 hostname
    assert diag.main() == 3


# ---- 不输出 Key / Authorization ----

class _DummySock:
    def close(self):
        pass


def test_main_never_prints_key(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["diagnose_ai_network.py"])
    monkeypatch.setenv("AI_BASE_URL", "http://example.test")  # http 跳过 TLS
    monkeypatch.setenv("AI_API_KEY", "SUPERSECRETKEY123")
    monkeypatch.setattr(diag, "_resolve_all", lambda host: ["8.8.8.8"])
    monkeypatch.setattr(diag.socket, "create_connection", lambda *a, **k: _DummySock())
    rc = diag.main()
    out = capsys.readouterr()
    blob = out.out + out.err
    assert "SUPERSECRETKEY123" not in blob
    assert "authorization" not in blob.lower()
    assert rc == 0


# ---- 子网重叠检测（纯函数）----

def test_overlap_single_ipv4():
    assert diag._addrs_in_subnet(["172.19.0.116"], "172.19.0.0/16") is True


def test_overlap_one_of_many():
    assert diag._addrs_in_subnet(["8.8.8.8", "172.19.0.5"], "172.19.0.0/16") is True


def test_overlap_none():
    assert diag._addrs_in_subnet(["8.8.8.8"], "172.28.10.0/24") is False


def test_overlap_ipv6():
    assert diag._addrs_in_subnet(["fd00::1"], "fd00::/8") is True
    assert diag._addrs_in_subnet(["2001:4860:4860::8888"], "fd00::/8") is False


def test_overlap_invalid_cidr():
    assert diag._addrs_in_subnet(["1.2.3.4"], "not-a-cidr") is False


def test_overlap_no_cidr():
    assert diag._addrs_in_subnet(["1.2.3.4"], None) is False
    assert diag._addrs_in_subnet(["1.2.3.4"], "") is False


# ---- --fail-on-overlap 退出码 ----

def test_fail_on_overlap_returns_4(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["diagnose_ai_network.py", "--fail-on-overlap"])
    monkeypatch.setenv("AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("CLIPMIND_DOCKER_SUBNET", "172.19.0.0/16")
    monkeypatch.setattr(diag, "_resolve_all", lambda host: ["172.19.0.5"])  # 落入子网
    monkeypatch.setattr(
        diag.socket, "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(OSError("No route to host")),
    )
    assert diag.main() == 4


def test_no_overlap_returns_0(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["diagnose_ai_network.py", "--fail-on-overlap"])
    monkeypatch.setenv("AI_BASE_URL", "http://example.test")  # http 跳过 TLS
    monkeypatch.setenv("CLIPMIND_DOCKER_SUBNET", "172.28.10.0/24")
    monkeypatch.setattr(diag, "_resolve_all", lambda host: ["8.8.8.8"])  # 不重叠
    monkeypatch.setattr(diag.socket, "create_connection", lambda *a, **k: _DummySock())
    assert diag.main() == 0


@pytest.mark.parametrize("net,expected", [(None, "172.28.10.0/24"), ("", "172.28.10.0/24")])
def test_docker_subnet_falls_back_to_default(monkeypatch, net, expected):
    monkeypatch.delenv("CLIPMIND_DOCKER_SUBNET", raising=False)
    assert diag._docker_subnet(net) == expected


def test_docker_subnet_uses_env(monkeypatch):
    monkeypatch.setenv("CLIPMIND_DOCKER_SUBNET", "10.240.50.0/24")
    assert diag._docker_subnet(None) == "10.240.50.0/24"

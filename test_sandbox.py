"""SandboxExecutor birim testleri — güvenli ve tehlikeli komut senaryoları."""

import shutil

import pytest

from gatekeeper import SandboxExecutor

sx = SandboxExecutor()


# ── Güvenli komutlar ──────────────────────────────────────────────────────────

def test_echo_success():
    ok, out = sx.run("echo merhaba")
    assert ok
    assert "merhaba" in out


def test_pwd_success():
    ok, out = sx.run("pwd")
    assert ok
    assert "/" in out


def test_python_print():
    ok, out = sx.run("python3 -c 'print(\"theia\")'")
    assert ok
    assert "theia" in out


def test_nonexistent_command():
    ok, out = sx.run("komut_yok_xyz_123")
    assert not ok
    assert "bulunamadı" in out.lower() or "not found" in out.lower()


def test_empty_command():
    ok, out = sx.run("")
    assert not ok


def test_timeout(tmp_path):
    ok, out = sx.run("sleep 30")
    assert not ok
    assert "zaman aşımı" in out.lower() or "timeout" in out.lower()


# ── Engellenen komutlar ───────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "rm foo.txt",
    "dd if=/dev/zero of=/tmp/x",
    "mkfs.ext4 /dev/sdb",
    "shred file.txt",
    "chmod 777 /tmp/x",
    "chown root /tmp/x",
    "kill -9 1",
    "reboot",
    "shutdown -h now",
    "systemctl stop sshd",
])
def test_blocked_executables(cmd):
    ok, out = sx.run(cmd)
    assert not ok
    assert "engellenen" in out.lower()


# ── Tehlikeli Python kodu engelleme ───────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "import os; os.system('ls')",
    "import subprocess; subprocess.run(['ls'])",
    "import sys; sys.exit()",
    "import shutil; shutil.rmtree('/tmp')",
    "eval('1+1')",
    "exec('x=1')",
    "__import__('os')",
])
def test_blocked_python_code(code):
    ok, out = sx.run(f"python3 -c \"{code}\"")
    assert not ok, f"Bu kod engellenmeli: {code!r}"
    assert "tehlikeli" in out.lower()


# ── Güvenli Python kodu ───────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "print(2 + 2)",
    "x = [i**2 for i in range(5)]; print(x)",
    "import math; print(math.pi)",
    "import json; print(json.dumps({'a': 1}))",
])
def test_safe_python_code(code):
    ok, out = sx.run(f"python3 -c \"{code}\"")
    assert ok, f"Bu kod geçmeli: {code!r} — çıktı: {out}"


# ── Parse hatası ──────────────────────────────────────────────────────────────

def test_malformed_quotes():
    ok, out = sx.run("echo 'unclosed")
    assert not ok
    assert "parse" in out.lower() or "hata" in out.lower()


# ── Docker smoke test ─────────────────────────────────────────────────────────

def _docker_compose_available() -> bool:
    """docker compose (v2) subcommand'ının çalışıp çalışmadığını kontrol eder."""
    if shutil.which("docker") is None:
        return False
    import subprocess as _sp
    try:
        r = _sp.run(["docker", "compose", "version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


_docker_available = _docker_compose_available()


@pytest.mark.skipif(not _docker_available, reason="docker compose (v2) kurulu değil")
def test_docker_sandbox_echo():
    sx_docker = SandboxExecutor(use_docker=True)
    ok, out = sx_docker.run("echo docker-sandbox")
    assert ok, f"Docker sandbox echo başarısız — çıktı: {out}"
    assert "docker-sandbox" in out

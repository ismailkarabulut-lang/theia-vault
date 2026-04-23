"""THEIA Gatekeeper — risk sınıflandırma, sandbox yürütme, denetim logu."""

import ast
import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

AUDIT_LOG_PATH = Path.home() / "theia" / "gatekeeper_log.json"


class Risk(str, Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ClassifyResult:
    risk:   Risk
    reason: str


class RiskClassifier:
    # (pattern, reason) — sırayla kontrol edilir, ilk eşleşen kazanır

    _INJECTION = [
        (r";\s*rm\b",        "injection: ; rm"),
        (r"&&\s*sudo\b",     "injection: && sudo"),
        (r"\|\s*(ba)?sh\b",  "injection: | sh/bash"),
        (r"`[^`]+`",         "komut ikamesi: backtick"),
        (r"\$\([^)]+\)",     "komut ikamesi: $()"),
    ]

    _CRITICAL = [
        (r"\brm\b.{0,30}-[A-Za-z]*r[A-Za-z]*\s+/\s*$",   "rm -rf / (kök dizin)"),
        (r"\brm\b.{0,30}-[A-Za-z]*r[A-Za-z]*\s+/\*",      "rm -rf /* (kök içerik)"),
        (r"\bdd\b.*if=/dev/zero.*of=/dev/[hs]d",           "dd ile disk silme"),
        (r"\bmkfs\b",                                       "disk formatlama"),
        (r":\(\)\s*\{.*\|.*:.*&",                          "fork bomb"),
        (r">\s*/dev/[hs]d[a-z]",                           "direk disk yazma"),
    ]

    _HIGH = [
        (r"\brm\b.{0,30}-[A-Za-z]*r[A-Za-z]*\b",  "rm -rf (özyinelemeli silme)"),
        (r"\bsudo\s+rm\b",                          "sudo rm"),
        (r"\bDROP\s+TABLE\b",                       "SQL: DROP TABLE"),
        (r"\bDELETE\s+FROM\b",                      "SQL: DELETE FROM"),
        (r"\bshred\b",                              "shred (güvenli silme)"),
        (r"\btruncate\b",                           "truncate"),
    ]

    _MEDIUM = [
        (r"\bapt\s+(install|remove|purge|upgrade)\b",       "apt paket yönetimi"),
        (r"\bpip\s+install\b",                              "pip install"),
        (r"\bnpm\s+(install|uninstall)\b",                  "npm paket yönetimi"),
        (r"\bsystemctl\s+(stop|disable|mask|kill|restart)\b","systemctl değiştirme"),
        (r"\bmv\b",                                         "mv (dosya taşıma/üzerine yazma)"),
        (r"\bcp\b.{0,15}-r\b",                             "cp -r (özyinelemeli kopyalama)"),
        (r"\bsudo\b",                                       "sudo yetkili çalıştırma"),
        (r"\bchmod\b",                                      "chmod (izin değiştirme)"),
        (r"\bchown\b",                                      "chown (sahip değiştirme)"),
        (r"\bdocker\b",                                     "docker"),
        (r"\bcurl\b.*\|",                                   "curl | pipe"),
        (r"\bwget\b",                                       "wget"),
        (r"\bgit\s+(push|reset|rebase|force)\b",           "git yıkıcı işlem"),
    ]

    _LOW = re.compile(
        r"^\s*(ls|ll|la|cat|pwd|ps|df|free|grep|find|echo|uname|whoami|"
        r"hostname|date|uptime|which|type|file|stat|head|tail|wc|sort|"
        r"uniq|printenv|env|id|groups|lsof|netstat|ss|ping|nslookup|"
        r"dig|history|alias|man|less|more|diff|du|lscpu|lsblk|"
        r"python3?\s+-c\s+['\"]?print)\b"
    )

    def classify(self, cmd: str) -> ClassifyResult:
        # Injection kontrolü → HIGH'a yükselt
        for pat, reason in self._INJECTION:
            if re.search(pat, cmd, re.IGNORECASE):
                return ClassifyResult(Risk.HIGH, f"Şüpheli kombinasyon: {reason}")

        for pat, reason in self._CRITICAL:
            if re.search(pat, cmd, re.IGNORECASE):
                return ClassifyResult(Risk.CRITICAL, reason)

        for pat, reason in self._HIGH:
            if re.search(pat, cmd, re.IGNORECASE):
                return ClassifyResult(Risk.HIGH, reason)

        for pat, reason in self._MEDIUM:
            if re.search(pat, cmd, re.IGNORECASE):
                return ClassifyResult(Risk.MEDIUM, reason)

        if self._LOW.match(cmd):
            return ClassifyResult(Risk.LOW, "Salt okunur / bilgi komutu")

        return ClassifyResult(Risk.MEDIUM, "Bilinmeyen komut — ihtiyatlı yaklaşım")


_BLOCKED_EXECUTABLES = frozenset({
    "rm", "dd", "mkfs", "shred", "chmod", "chown",
    "kill", "reboot", "shutdown", "systemctl",
})

_BLOCKED_PYTHON_MODULES = frozenset({
    "os", "subprocess", "shutil", "sys", "socket", "ctypes",
    "importlib", "builtins", "signal",
})

_BLOCKED_PYTHON_BUILTINS = frozenset({"eval", "exec", "__import__", "compile"})


def _check_python_ast(code: str) -> tuple[bool, str]:
    """Python kod stringini ast ile analiz eder, tehlikeli yapıları engeller."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return True, ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_PYTHON_MODULES:
                    return False, f"Tehlikeli import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _BLOCKED_PYTHON_MODULES:
                return False, f"Tehlikeli import: {node.module}"
        elif isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in _BLOCKED_PYTHON_BUILTINS:
                return False, f"Tehlikeli fonksiyon: {name}()"
    return True, ""


class SandboxExecutor:
    TIMEOUT = 10

    def run(self, cmd: str) -> tuple[bool, str]:
        """shell=False, timeout=10s. Pipe/yönlendirme desteklenmez."""
        try:
            args = shlex.split(cmd)
        except ValueError as e:
            return False, f"Parse hatası: {e}"
        if not args:
            return False, "Boş komut."

        executable      = Path(args[0]).name
        executable_base = executable.split(".")[0]
        if executable_base in _BLOCKED_EXECUTABLES:
            return False, f"Engellenen komut: {executable!r}"

        if executable_base in ("python", "python3") or executable in ("python", "python3"):
            for flag in ("-c", "--command"):
                if flag in args:
                    idx = args.index(flag)
                    if idx + 1 < len(args):
                        safe, reason = _check_python_ast(args[idx + 1])
                        if not safe:
                            return False, f"Tehlikeli Python kodu tespit edildi: {reason}"

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT,
                shell=False,
            )
            out = result.stdout
            if result.stderr.strip():
                out += f"\n[stderr]\n{result.stderr}"
            return result.returncode == 0, out.strip() or "(çıktı yok)"
        except FileNotFoundError:
            return False, f"Komut bulunamadı: {args[0]!r}"
        except subprocess.TimeoutExpired:
            return False, f"Zaman aşımı ({self.TIMEOUT}s)"
        except PermissionError:
            return False, "İzin reddedildi."
        except Exception as e:
            return False, f"Hata: {e}"


class AuditLog:
    def __init__(self, path: Path = AUDIT_LOG_PATH):
        self.path = path

    def write(self, cmd: str, risk: str, decision: str, output: str = "") -> None:
        entry = {
            "ts":             datetime.now().isoformat(timespec="seconds"),
            "cmd":            cmd,
            "risk":           risk,
            "decision":       decision,
            "output_preview": output[:200],
        }
        records: list = []
        if self.path.exists():
            try:
                records = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                records = []
        records.append(entry)
        self.path.write_text(json.dumps(records, ensure_ascii=False, indent=2))

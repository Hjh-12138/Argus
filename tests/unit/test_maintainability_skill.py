import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "argus-code-maintainability-scan" / "implementation"))
from main import invoke, main  # noqa: E402
from agents.code.detector import CodeDetector
from core.schemas import SnapshotFile, SourceSnapshot


def _payload(tmp_path, files):
    snaps = []
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        snaps.append({"path": rel, "sha256": "0" * 64, "size": len(content)})
    return {"schema_version": "1", "run_id": "r", "snapshot_id": "s",
            "source_root": str(tmp_path), "files": snaps}


def test_invoke_detects_magic_number(tmp_path):
    payload = _payload(tmp_path, {"app/pricing.py": "def calc(price):\n    return price * 0.8\n"})
    result = invoke(payload)
    assert result["status"] == "completed"
    assert any(f["category"] == "code.magic_number" for f in result["findings"])


def test_invoke_ignores_non_python(tmp_path):
    payload = _payload(tmp_path, {"app/app.js": "const x = 0.8;\n"})
    assert invoke(payload)["findings"] == []


def test_invoke_finding_has_p4_shape(tmp_path):
    payload = _payload(tmp_path, {"app/pricing.py": "def calc(price):\n    return price * 0.8\n"})
    f = invoke(payload)["findings"][0]
    assert f["agent"] == "code"
    assert f["evidence"]["source_sha256"] == "0" * 64
    assert f["fingerprint"].startswith(("0", "1", "2", "3", "4", "5", "6", "7",
                                        "8", "9", "a", "b", "c", "d", "e", "f"))


def test_main_writes_output(tmp_path):
    payload = _payload(tmp_path, {"a.py": "def f(x):\n    return x\n"})
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps(payload), encoding="utf-8")
    rc = main(["--input", str(in_path), "--output", str(out_path)])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["status"] == "completed"


def test_main_invalid_input_exit2(tmp_path):
    in_path = tmp_path / "bad.json"
    out_path = tmp_path / "out.json"
    in_path.write_text("not json", encoding="utf-8")
    rc = main(["--input", str(in_path), "--output", str(out_path)])
    assert rc == 2
    assert json.loads(out_path.read_text(encoding="utf-8"))["status"] == "failed"


# Corpus triggers every maintainability rule (CODE-101..CODE-111) exactly
# once per side so the parity key-set is exactly the 11 rules, non-empty.
_SMELLY = (
    "def long_fn():\n"
    + "".join("    x = x + 1\n" for _ in range(105))
    + "\n"
    "def process(aaa, bbb, ccc, ddd, eee, fff, ggg):\n"
    "    return aaa\n"
    "\n"
    "def deep():\n"
    "    if aaa:\n"
    "        for bbb in ccc:\n"
    "            while ddd:\n"
    "                if eee:\n"
    "                    pass\n"
    "\n"
    "def flags():\n"
    "    is_active = True\n"
    "    is_ready = True\n"
    "    is_done = True\n"
    "    return is_active and is_ready and is_done\n"
    "\n"
    "def calc(price):\n"
    "    return price * 0.8\n"
    "\n"
    "def order_is_active(status):\n"
    '    if status == "pending":\n        return True\n'
    '    if status == "paid":\n        return True\n'
    '    if status == "shipped":\n        return True\n'
    "    return False\n"
    "\n"
    "def label(code):\n"
    '    if code == "A":\n        return "A"\n'
    '    elif code == "B":\n        return "B"\n'
    '    elif code == "C":\n        return "C"\n'
    '    elif code == "D":\n        return "D"\n'
    '    return "?"\n'
    "\n"
    "def is_privileged(role):\n"
    '    if role == "ADMIN" or role == "EDITOR" or role == "OWNER":\n'
    "        return True\n"
    "    return False\n"
    "\n"
    "names = ['a', 'b']\n"
    "scores = [1, 2]\n"
    "for i in range(len(names)):\n"
    "    total = names[i] + scores[i]\n"
    "\n"
    "orders = []\n"
    "users = []\n"
    "for o in orders:\n"
    "    for u in users:\n"
    "        if o.uid == u.id:\n"
    "            found = o\n"
    "\n"
    "def add(x):\n"
    "    return x\n"
)


def _detector_keys(tmp_path, text):
    snap = SourceSnapshot(
        root=str(tmp_path),
        files=(SnapshotFile(path="app/pricing.py", sha256="0" * 64, size=len(text)),),
    )
    return {(f.agent, f.category, f.file, f.line_start)
            for f in CodeDetector().detect(snap)
            if f.category != "code.placeholder"}


def test_parity_skill_vs_host_detector(tmp_path):
    p = tmp_path / "app"
    p.mkdir(parents=True)
    (p / "pricing.py").write_text(_SMELLY, encoding="utf-8")
    payload = _payload(tmp_path, {"app/pricing.py": _SMELLY})
    skill_keys = {(f["agent"], f["category"], f["file"], f["line_start"])
                  for f in invoke(payload)["findings"]}
    assert skill_keys == _detector_keys(tmp_path, _SMELLY)
    assert skill_keys  # non-empty: the corpus triggers rules on both sides

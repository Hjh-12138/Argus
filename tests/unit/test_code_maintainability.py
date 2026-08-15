import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "argus-code-maintainability-scan" / "implementation"))
from rules import scan_path

# 文件顶部追加 import
from core.schemas import SnapshotFile, SourceSnapshot
from agents.code.detector import CodeDetector


def _snap(tmp_path, files):
    snaps = []
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        snaps.append(SnapshotFile(path=rel, sha256="0" * 64, size=len(content)))
    return SourceSnapshot(root=str(tmp_path), files=tuple(snaps))


def _hits(text):
    return scan_path("app/a.py", text)


def test_101_long_function_detected():
    text = "def long_fn():\n" + "".join(f"    x = x + {i % 3}\n" for i in range(105))
    assert any(h.rule_id == "CODE-101" for h in _hits(text))


def test_101_short_function_ok():
    assert not any(h.rule_id == "CODE-101" for h in _hits("def f():\n    return 1\n"))


def test_102_too_many_params_detected():
    assert any(h.rule_id == "CODE-102"
               for h in _hits("def f(a, b, c, d, e, g, h):\n    return a\n"))


def test_102_params_within_limit_ok():
    assert not any(h.rule_id == "CODE-102"
                   for h in _hits("def f(a, b, c, d, e, g):\n    return a\n"))


def test_111_single_letter_param_detected():
    assert any(h.rule_id == "CODE-111" for h in _hits("def f(x, y):\n    return x\n"))


def test_111_descriptive_params_ok():
    assert not any(h.rule_id == "CODE-111"
                   for h in _hits("def apply(amount, rate):\n    return amount\n"))


def test_scan_path_ignores_non_python():
    assert scan_path("app/app.js", "const x = 1;\n") == []


def test_103_deep_nesting_detected():
    text = ("if a:\n"
            "    if b:\n"
            "        if c:\n"
            "            if d:\n"
            "                return 1\n"
            "    return 0\n")
    assert any(h.rule_id == "CODE-103" for h in _hits(text))


def test_103_shallow_nesting_ok():
    text = "if a:\n    if b:\n        return 1\nreturn 0\n"
    assert not any(h.rule_id == "CODE-103" for h in _hits(text))


def test_106_three_bool_flags_detected():
    text = ("def run():\n"
            "    is_started = True\n"
            "    is_processing = False\n"
            "    is_finished = False\n"
            "    return 0\n")
    assert any(h.rule_id == "CODE-106" for h in _hits(text))


def test_106_two_bool_flags_ok():
    text = ("def run():\n"
            "    is_started = True\n"
            "    is_finished = False\n"
            "    return 0\n")
    assert not any(h.rule_id == "CODE-106" for h in _hits(text))


def test_104_magic_number_detected():
    assert any(h.rule_id == "CODE-104"
               for h in _hits("def calc(price):\n    return price * 0.8\n"))


def test_104_whitelisted_number_ok():
    assert not any(h.rule_id == "CODE-104"
                   for h in _hits("def calc(price):\n    return price + 1\n"))


def test_104_name_times_name_ok():
    assert not any(h.rule_id == "CODE-104"
                   for h in _hits("def calc(a, b):\n    return a * b\n"))


def test_105_bare_string_enum_detected():
    text = ("def label(status):\n"
            '    if status == "pending":\n        return True\n'
            '    if status == "paid":\n        return True\n'
            '    if status == "shipped":\n        return True\n'
            "    return False\n")
    assert any(h.rule_id == "CODE-105" for h in _hits(text))


def test_105_less_than_three_values_ok():
    text = ("def label(status):\n"
            '    if status == "pending":\n        return True\n'
            '    if status == "paid":\n        return True\n'
            "    return False\n")
    assert not any(h.rule_id == "CODE-105" for h in _hits(text))


def test_107_mapping_if_chain_detected():
    text = ("def discount(t):\n"
            '    if t == "normal":\n        return 1.0\n'
            '    elif t == "vip":\n        return 0.8\n'
            '    elif t == "svip":\n        return 0.7\n'
            '    elif t == "employee":\n        return 0.5\n'
            "    return 1.0\n")
    assert any(h.rule_id == "CODE-107" for h in _hits(text))


def test_107_three_branch_ok():
    text = ("def discount(t):\n"
            '    if t == "normal":\n        return 1.0\n'
            '    elif t == "vip":\n        return 0.8\n'
            '    elif t == "svip":\n        return 0.7\n'
            "    return 1.0\n")
    assert not any(h.rule_id == "CODE-107" for h in _hits(text))


def test_108_or_chain_detected():
    text = ('def has(role):\n'
            '    if role == "admin" or role == "owner" or role == "superuser":\n'
            "        return True\n"
            "    return False\n")
    assert any(h.rule_id == "CODE-108" for h in _hits(text))


def test_108_two_branch_ok():
    text = ('def has(role):\n'
            '    if role == "admin" or role == "owner":\n'
            "        return True\n"
            "    return False\n")
    assert not any(h.rule_id == "CODE-108" for h in _hits(text))


def test_109_parallel_arrays_detected():
    text = ("names = ['a', 'b']\n"
            "ages = [1, 2]\n"
            "emails = ['x', 'y']\n"
            "for i in range(len(names)):\n"
            "    print(names[i], ages[i], emails[i])\n")
    assert any(h.rule_id == "CODE-109" for h in _hits(text))


def test_109_single_list_ok():
    text = ("names = ['a', 'b']\n"
            "for i in range(len(names)):\n"
            "    print(names[i])\n")
    assert not any(h.rule_id == "CODE-109" for h in _hits(text))


def test_110_linear_scan_detected():
    text = ("users = [{'id': 1}, {'id': 2}]\n"
            "orders = [{'uid': 1}]\n"
            "for o in orders:\n"
            "    for u in users:\n"
            "        if o.uid == u.id:\n"
            "            print(o)\n")
    assert any(h.rule_id == "CODE-110" for h in _hits(text))


def test_110_no_nested_join_ok():
    text = ("users = []\n"
            "for u in users:\n"
            "    print(u)\n")
    assert not any(h.rule_id == "CODE-110" for h in _hits(text))


# 文件末尾追加用例
def test_detector_emits_maintainability_finding(tmp_path):
    snap = _snap(tmp_path, {"app/pricing.py":
        "def calc(price):\n    return price * 0.8\n"})
    assert any(f.category == "code.magic_number"
               for f in CodeDetector().detect(snap))


def test_detector_clean_code_no_maintainability(tmp_path):
    snap = _snap(tmp_path, {"app/pricing.py":
        "def apply(amount, rate):\n    return amount * rate\n"})
    assert not any(f.category.startswith("code.") and f.category != "code.placeholder"
                   for f in CodeDetector().detect(snap))


def test_detector_finding_carries_p4_evidence(tmp_path):
    snap = _snap(tmp_path, {"app/pricing.py":
        "def calc(price):\n    return price * 0.8\n"})
    f = next(f for f in CodeDetector().detect(snap)
             if f.category == "code.magic_number")
    assert f.evidence.source_sha256 == "0" * 64
    assert f.agent == "code"
    assert f.rule_id == "CODE-104"

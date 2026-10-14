"""`hle_keep_original`: an hle_func routine also keeps its compiled original.

Pins the contract documented in docs/HLE_FUNC.md, "Keeping the compiled
original":

* the original body is emitted from the ROM bytes, as a plain build would
  emit it, under `<Name>_orig_M<m>X<x>`, for exactly the variants the
  analysis compiles; a back-edge to its own entry stays a local goto;
* it owns no dispatch slot and gets no void alias: every caller, the
  dispatch row and runtime lookups keep reaching the forwarding stub;
* inside it, other hle_func PCs remain boundaries (calls reach their stubs);
* `hle_original_v2.c` lists it in `g_hle_original_table`, always emitted;
* the stub of a kept routine records its arrival
  (`cpu_hle_take_arrival_context`), other stubs are unchanged;
* the cfg directive needs an hle_func at the same PC.
"""
import pathlib
import re
import subprocess
import sys

import pytest

from v2.cfg_loader import load_bank_cfg


REPO = pathlib.Path(__file__).resolve().parents[2]


def _rom() -> bytes:
    rom = bytearray([0xFF] * 0x8000)

    def put(pc, data):
        rom[pc - 0x8000:pc - 0x8000 + len(data)] = bytes(data)

    put(0x8000, [0x20, 0x00, 0x81,                  # JSR CallerJsr
                 0x20, 0x00, 0x82,                  # JSR CallerJmp
                 0x20, 0x00, 0x92,                  # JSR KeptCalls
                 0x60])
    put(0x8100, [0x20, 0x00, 0x90, 0x60])           # JSR Kept ; RTS
    put(0x8200, [0x4C, 0x00, 0x90])                 # JMP Kept
    put(0x9000, [0xC6, 0x10, 0xD0, 0xFC, 0x60])     # Kept: DEC $10 ; BNE Kept ; RTS
    put(0x9100, [0x60])                             # Other: RTS
    put(0x9200, [0x20, 0x00, 0x91, 0x60])           # KeptCalls: JSR Other ; RTS
    rom[0x7FFC:0x7FFE] = bytes([0x00, 0x80])
    rom[0x7FEA:0x7FEC] = bytes([0xFF, 0xFF])
    rom[0x7FEE:0x7FF0] = bytes([0xFF, 0xFF])
    return bytes(rom)


def _emit(tmp_path, keep=True, no_hle=False):
    (tmp_path / "game.sfc").write_bytes(_rom())
    cfg_dir = tmp_path / "recomp"
    cfg_dir.mkdir()
    lines = [
        "bank = 00",
        "func I_RESET 8000 end:800a entry_mx:1,1",
        "func CallerJsr 8100 end:8104 entry_mx:1,1",
        "func CallerJmp 8200 end:8203 entry_mx:1,1",
        "func Kept 9000 end:9005 entry_mx:1,1",
        "func Other 9100 end:9101 entry_mx:1,1",
        "func KeptCalls 9200 end:9204 entry_mx:1,1",
        "hle_func 9000 HleKept",
        "hle_func 9100 HleOther",
        "hle_func 9200 HleKeptCalls",
    ]
    if keep:
        lines.append("hle_keep_original 9000 9200")
    (cfg_dir / "bank00.cfg").write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")
    out_dir = tmp_path / "gen"
    cmd = [sys.executable, str(REPO / "tools" / "v2_emit.py"),
           "--rom", str(tmp_path / "game.sfc"), "--cfg-dir", str(cfg_dir),
           "--out-dir", str(out_dir), "--no-host-root-scan"]
    if no_hle:
        cmd.append("--no-hle")
    result = subprocess.run(cmd, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return out_dir


def _bodies(out_dir):
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted(out_dir.glob("bank*_v2.c")))


def _function_body(source, name):
    match = re.search(
        r"^RecompReturn " + re.escape(name) + r"\(CpuState \*cpu\) \{\n"
        r"(.*?)^\}\n", source, re.S | re.M)
    assert match, f"{name} not emitted"
    return match.group(1)


def test_kept_original_is_emitted_beside_the_stub(tmp_path):
    out_dir = _emit(tmp_path)
    banks = _bodies(out_dir)
    dispatch = (out_dir / "dispatch_v2.c").read_text(encoding="utf-8")
    table = (out_dir / "hle_original_v2.c").read_text(encoding="utf-8")

    # The original body: the ROM bytes, compiled; its back-edge to its own
    # entry is a local goto, not a transfer to the stub.
    orig = _function_body(banks, "Kept_orig_M1X1")
    assert re.search(r"^\s*L_9000_M1X1:", orig, re.M)
    assert "goto L_9000_M1X1;" in orig
    assert "Kept_M1X1(cpu)" not in orig and "HleKept" not in orig
    assert "RTS pop hardware return frame" in orig
    # Inside a kept original, another hle_func PC is still a boundary.
    calls = _function_body(banks, "KeptCalls_orig_M1X1")
    assert re.search(r"\bOther_M1X1\(cpu\)", calls)
    assert "HleOther" not in calls

    # Stubs: all four variants still forward to the helper; a kept routine's
    # stub records its arrival, the others keep the plain swallow.
    for m in (0, 1):
        for x in (0, 1):
            kept = _function_body(banks, f"Kept_M{m}X{x}")
            assert "RecompReturn _r = HleKept(cpu);" in kept
            assert "cpu_hle_take_arrival_context();" in kept
            assert "cpu_take_tailcall_return_context" not in kept
            other = _function_body(banks, f"Other_M{m}X{x}")
            assert "cpu_take_tailcall_return_context(NULL, NULL);" in other
            assert "cpu_hle_take_arrival_context" not in other

    # Callers and the dispatch row keep reaching the stub.
    assert re.search(r"\bKept_M1X1\(cpu\)", _function_body(banks, "CallerJsr_M1X1"))
    assert re.search(r"\bKept_M1X1\(cpu\)", _function_body(banks, "CallerJmp_M1X1"))
    assert "Kept_M0X0, Kept_M0X1, Kept_M1X0, Kept_M1X1" in dispatch
    assert "_orig" not in dispatch
    # No host alias for the original.
    assert not re.search(r"^void Kept_orig\(", banks, re.M)

    # The table: one row per kept PC, only the analysed variant (M1X1).
    assert re.search(r"\{ 0x[08]09000u, \{ NULL, NULL, NULL, Kept_orig_M1X1 \}, 0 \}",
                     table)
    assert re.search(r"\{ 0x[08]09200u, \{ NULL, NULL, NULL, KeptCalls_orig_M1X1 \}, 0 \}",
                     table)
    assert "Other" not in table
    assert "const unsigned g_hle_original_table_count = 2u;" in table


def test_without_the_directive_nothing_changes(tmp_path):
    out_dir = _emit(tmp_path, keep=False)
    banks = _bodies(out_dir)
    table = (out_dir / "hle_original_v2.c").read_text(encoding="utf-8")
    assert "_orig" not in banks
    assert "cpu_hle_take_arrival_context" not in banks
    assert "const unsigned g_hle_original_table_count = 0u;" in table
    assert "{ 0xFFFFFFu, { NULL, NULL, NULL, NULL }, 0 }" in table


def test_no_hle_build_keeps_no_original(tmp_path):
    out_dir = _emit(tmp_path, keep=True, no_hle=True)
    banks = _bodies(out_dir)
    table = (out_dir / "hle_original_v2.c").read_text(encoding="utf-8")
    # The plain build compiles the routine itself under its own name.
    assert re.search(r"^\s*L_9000_M1X1:", _function_body(banks, "Kept_M1X1"), re.M)
    assert "_orig" not in banks
    assert "const unsigned g_hle_original_table_count = 0u;" in table


def test_cfg_requires_an_hle_func_at_the_same_pc(tmp_path):
    good = tmp_path / "bank00.cfg"
    good.write_text("bank = 00\nhle_func 9000 HleKept\n"
                    "hle_keep_original 9000\n", encoding="utf-8")
    assert load_bank_cfg(str(good)).hle_keep_original == {0x9000}
    bad = tmp_path / "bank01.cfg"
    bad.write_text("bank = 01\nhle_func 9000 HleKept\n"
                   "hle_keep_original 9100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="without an hle_func"):
        load_bank_cfg(str(bad))

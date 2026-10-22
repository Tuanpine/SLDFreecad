#!/usr/bin/env python3
"""
sw2step.py - Chuyển SolidWorks (.sldprt / .sldasm / .slddrw) sang STEP (.step), DXF, SVG
             và Mở trực tiếp trong FreeCAD (hỗ trợ bản vẽ nhiều tờ, màu AP214, font CAD, tách Layer 2D).

TÍCH HỢP MỞ TRỰC TIẾP TRONG FREECAD (khuyên dùng - chỉ cần cài 1 lần):
  Cách A (từ Terminal / CMD):
      python sw2step.py --setup --install-freecad
  Cách B (không cần gõ lệnh):
      Mở FreeCAD -> Macro -> Macros... -> chọn file sw2step.py -> Execute.
      Script sẽ tự cài plugin vào FreeCAD, kích hoạt ngay lập tức (không cần khởi động lại)
      và mở hộp thoại chọn file .SLDPRT / .SLDASM / .SLDDRW.

  Sau khi cài, bạn có thể:
    - Bấm Ctrl+O (File -> Open) hoặc File -> Import trong FreeCAD để mở thẳng
      .SLDPRT, .SLDASM và cả bản vẽ .SLDDRW
    - Kéo-thả (Drag & Drop) file .SLDPRT / .SLDASM / .SLDDRW trực tiếp vào cửa sổ FreeCAD
    - Click đúp file .SLDPRT / .SLDASM / .SLDDRW trong File Explorer (chọn Open with -> FreeCAD)

Điểm nổi bật (v3):
  - .sldprt (Part 3D)     : Chuyển sang B-rep STEP + trích xuất màu vật liệu/body từ SolidWorks
                            nhúng vào STEP AP214 (STYLED_ITEM / COLOUR_RGB).
  - .sldasm (Assembly 3D) : Chuyển sang B-rep STEP giữ nguyên cấu trúc lắp ghép & màu sắc.
  - .slddrw (Drawing 2D)  : Giải mã trực tiếp container GContainer bằng thuần Python:
      1) Hỗ trợ bản vẽ nhiều tờ (Multi-Sheet): tự động tách Sheet1, Sheet2,... và dàn hàng ngang
         (không bị gộp chồng lên nhau), hỗ trợ chọn tờ qua --sheet.
      2) Phân lớp Layer rõ ràng để bật/tắt bằng phím Space trong FreeCAD / AutoCAD:
           - 01_Khung_Ban_Ve (BORDER)     : Khung giấy, khung tên, bảng biểu
           - 02_Hinh_Chieu   (VIEWS)      : Đường nét các hình chiếu 2D
           - 03_Kich_Thuoc   (DIMENSIONS) : Đường gióng, đường kích thước, mũi tên & số đo
           - 04_Chu_Ghi_Chu  (TEXT_NOTES) : Chữ khung tên, ghi chú kỹ thuật
           - 05_Model_3D     (MODEL_3D)   : Mô hình 3D nhúng sẵn (tự ẩn mặc định khi mở bản vẽ 2D)
      3) Bộ font vector CAD 95 ký tự nét mượt, tỷ lệ biến thiên (hỗ trợ chữ thường a-z, đúng cỡ chữ
         pt của SolidWorks và đầy đủ ký hiệu cơ khí: Ø, ±, °, ×, ≤, ≥, µ, ⊥, ∥, ⌖, ⌴, ⌵, ↧).
      4) Khi mở .SLDDRW trong FreeCAD: tự động gom nhóm Layer, ẩn khối 3D để nhìn thẳng bản vẽ 2D,
         đồng thời tạo trang bản vẽ 2D gốc (TechDraw::DrawPage) cho từng tờ.

Ví dụ dòng lệnh:
    python sw2step.py --setup --install-freecad
    python sw2step.py 2.SLDDRW --open
    python sw2step.py 2.SLDDRW --ext dxf
    python sw2step.py 2.SLDDRW --ext svg --sheet 1
    python sw2step.py 2.SLDDRW --inspect
    python sw2step.py part.sldprt --open
    python sw2step.py D:\\cad -r -o D:\\step_out --jobs 4 --report report.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import html
import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("sw2step")

EXT_PART = ".sldprt"
EXT_ASM = ".sldasm"
EXT_DRW = ".slddrw"
SUPPORTED = (EXT_PART, EXT_ASM, EXT_DRW)
# Tăng khi đổi logic chuyển đổi: vừa để biết FreeCAD đang chạy bản nào, vừa làm mất hiệu lực cache cũ.
SW2STEP_VERSION = "2026.10.22-v3"

# --------------------------------------------------------------------------- #
# Cấu hình backend opensource & Bộ nhớ đệm (Cache)
# --------------------------------------------------------------------------- #
TOOLS_HOME = Path(os.environ.get("SW2STEP_HOME", Path.home() / ".sw2step"))
CACHE_DIR = TOOLS_HOME / "cache"
REPOS = {
    "sld2step": ("https://github.com/dsandall/sld2step.git",
                 "bb7674d7de80a7fbe6d3636c11cb7b38745dd8c7"),
    "sldprt2step": ("https://github.com/BlinkingSun/sldprt2step.git",
                    "fa954124f4f126e0c465c8f96454978ac80b812e"),
}
PY_MIN, PY_MAX = (3, 10), (3, 14)      # theo wheel cadquery-ocp-novtk 7.9.x (win_amd64)
VENV_DIR = TOOLS_HOME / "venv"
VENV_PY = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SLD2STEP = TOOLS_HOME / "sld2step" / "sld2step.py"
SLDASM2STEP = TOOLS_HOME / "sld2step" / "sldasm2step.py"
SLDPRT2STEP = TOOLS_HOME / "sldprt2step" / "sldprt2step.py"

ANSI = re.compile(r"\x1b\[[0-9;]*m")

_VALIDATE_SRC = r'''
import sys, json
from OCP.STEPControl import STEPControl_Reader
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
r = STEPControl_Reader()
if int(r.ReadFile(sys.argv[1])) != 1:
    print(json.dumps({"valid": False, "volume": 0.0})); sys.exit(0)
r.TransferRoots()
s = r.OneShape()
if s.IsNull():
    print(json.dumps({"valid": False, "volume": 0.0})); sys.exit(0)
p = GProp_GProps(); BRepGProp.VolumeProperties_s(s, p)
print(json.dumps({"valid": bool(BRepCheck_Analyzer(s).IsValid()), "volume": p.Mass()}))
'''

# Gộp trích xuất ImportedComp/* và chạy sldasm2step.py trong 1 tiến trình Python duy nhất
_ASM_RUNNER_SRC = r'''
import sys, runpy
from pathlib import Path

sld2step_dir, asm_path, emb_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
rest_args = sys.argv[4:]
sys.path.insert(0, sld2step_dir)

import sldload
c = sldload.open_container(asm_path)
n = 0
for b in c.blobs:
    if b.name.startswith("ImportedComp/"):
        emb_dir.mkdir(parents=True, exist_ok=True)
        name = Path(b.name.split("/", 1)[1]).name
        d = b.data() if callable(b.data) else b.data
        (emb_dir / name).write_bytes(bytes(d))
        n += 1
print("EMBEDDED", n, flush=True)

cmd_args = [str(Path(sld2step_dir) / "sldasm2step.py"), asm_path] + rest_args
if n > 0:
    cmd_args += ["--root", str(emb_dir)]
sys.argv = cmd_args
runpy.run_path(cmd_args[0], run_name="__main__")
'''


@dataclass
class Result:
    src: Path
    dst: Path | None
    backend: str
    status: str          # OK | WARN | FAIL | SKIP
    note: str = ""
    seconds: float = 0.0


# --------------------------------------------------------------------------- #
# Tiện ích & Cache tốc độ cao
# --------------------------------------------------------------------------- #
def _kill_tree(proc: subprocess.Popen) -> None:
    """Dừng tiến trình và con cháu. Trên Windows, python.exe của venv là launcher sinh
    ra interpreter thật làm tiến trình con, nên proc.kill() một mình sẽ để sót."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            proc.kill()
    except Exception:
        pass


_LIVE: set[subprocess.Popen] = set()
_LIVE_LOCK = threading.Lock()


def kill_all_children() -> None:
    with _LIVE_LOCK:
        procs = list(_LIVE)
    for p in procs:
        _kill_tree(p)


def run(cmd: list, timeout: int) -> tuple[int, str]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    with subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8",
                          errors="replace", env=env, **kwargs) as p:
        with _LIVE_LOCK:
            _LIVE.add(p)
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(p)
            p.communicate()
            return 124, f"timeout sau {timeout}s"
        except BaseException:
            _kill_tree(p)
            raise
        finally:
            with _LIVE_LOCK:
                _LIVE.discard(p)
    return p.returncode, ANSI.sub("", (out or "") + "\n" + (err or ""))


def last_line(text: str, width: int = 200) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1][:width] if lines else ""


def place(src: Path, dst: Path) -> None:
    """Đặt file kết quả vào đích (ghi đè nếu đã có, kể cả file rỗng/hỏng từ lần trước)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))


def cache_path_for(src: Path, fasteners: bool = False, ext: str = "step",
                   sheet_filter: int | None = None) -> Path:
    """Tính đường dẫn file trong cache dựa theo đường dẫn, mtime_ns và kích thước file."""
    src_res = src.resolve()
    st = src_res.stat()
    h = hashlib.sha256()
    h.update(
        f"{src_res}|{st.st_mtime_ns}|{st.st_size}|fasteners={fasteners}"
        f"|ext={ext}|sheet={sheet_filter}|v={SW2STEP_VERSION}".encode("utf-8")
    )
    if src_res.suffix.lower() in (EXT_ASM, EXT_DRW):
        for p in sorted(src_res.parent.glob("*.[sS][lL][dD]*")):
            if p.suffix.lower() in SUPPORTED:
                try:
                    pst = p.stat()
                    h.update(f"|{p.name}:{pst.st_mtime_ns}:{pst.st_size}".encode("utf-8"))
                except OSError:
                    pass
    digest = h.hexdigest()[:20]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{src_res.stem}_{digest}.{ext}"


def collect_files(src: Path, recursive: bool) -> list[Path]:
    if src.is_file():
        return [src] if src.suffix.lower() in SUPPORTED else []
    it = src.rglob("*") if recursive else src.glob("*")
    return sorted(p for p in it
                  if p.is_file() and p.suffix.lower() in SUPPORTED
                  and not p.name.startswith("~$"))


def expand_inputs(items: list[Path], recursive: bool) -> list[Path] | None:
    """Mở rộng wildcard (cmd/PowerShell không tự expand). None nếu có đường dẫn sai."""
    out: list[Path] = []
    for item in items:
        s = str(item)
        if any(ch in s for ch in "*?["):
            hits = sorted(glob.glob(s, recursive=recursive))
            if not hits:
                log.error("Không có gì khớp mẫu: %s", s)
                return None
            out += [Path(h) for h in hits]
        else:
            out.append(item)
    return out


def plan_outputs(jobs: list[tuple[Path, Path]], output: Path | None, ext: str) -> list[Path]:
    """Tính đường dẫn đích. Nếu part/assembly/drawing cùng tên (X.SLDPRT + X.SLDASM + X.SLDDRW)
    sẽ trùng X.step, nên thêm hậu tố _part / _asm / _drw để không ghi đè lẫn nhau."""
    dsts = []
    for f, base in jobs:
        rel = f.relative_to(base)
        # dxf/svg chỉ có nghĩa với bản vẽ; part/assembly luôn xuất STEP (tránh file .dxf chứa dữ liệu STEP)
        e = ext if (ext in ("step", "stp") or f.suffix.lower() == EXT_DRW) else "step"
        dsts.append(((output.resolve() / rel) if output else f).with_suffix("." + e))
    groups: dict[str, list[int]] = {}
    for i, d in enumerate(dsts):
        groups.setdefault(str(d).lower(), []).append(i)
    suffix_map = {EXT_PART: "part", EXT_ASM: "asm", EXT_DRW: "drw"}
    for idxs in groups.values():
        if len(idxs) > 1:
            log.warning("Trùng tên đầu ra %s -> thêm hậu tố _part/_asm/_drw", dsts[idxs[0]].name)
            for i in idxs:
                kind = suffix_map.get(jobs[i][0].suffix.lower(), "out")
                dsts[i] = dsts[i].with_name(f"{dsts[i].stem}_{kind}{dsts[i].suffix}")
    return dsts


# --------------------------------------------------------------------------- #
# Bộ Font Vector CAD Tỷ lệ biến thiên (95 ký tự: A-Z, a-z, 0-9 & Ký hiệu cơ khí)
# --------------------------------------------------------------------------- #
def _arc_pts(cx: float, cy: float, rx: float, ry: float,
             a0_deg: float, a1_deg: float, n: int = 10) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for k in range(n + 1):
        a = math.radians(a0_deg + (a1_deg - a0_deg) * k / n)
        pts.append((round(cx + rx * math.cos(a), 4), round(cy + ry * math.sin(a), 4)))
    return pts


def _build_cad_font() -> dict[str, tuple[float, list[list[tuple[float, float]]]]]:
    """Khởi tạo bộ font kỹ thuật nét mượt (ISO/ASME simplex) gồm chiều rộng bước (advance width)
    và danh sách các nét vẽ trong khung chuẩn [0..1]."""
    g: dict[str, tuple[float, list[list[tuple[float, float]]]]] = {}
    # Chữ số 0-9
    g["0"] = (0.68, [_arc_pts(0.30, 0.70, 0.24, 0.30, 0, 180, 8) + _arc_pts(0.30, 0.30, 0.24, 0.30, 180, 360, 8) + [(0.54, 0.70)]])
    g["1"] = (0.48, [[(0.14, 0.80), (0.30, 1.00), (0.30, 0.00)], [(0.12, 0.00), (0.48, 0.00)]])
    g["2"] = (0.66, [_arc_pts(0.30, 0.74, 0.24, 0.26, 165, -35, 10) + [(0.06, 0.00), (0.56, 0.00)]])
    g["3"] = (0.66, [_arc_pts(0.29, 0.76, 0.22, 0.24, 160, -90, 9), _arc_pts(0.29, 0.26, 0.24, 0.26, 90, -160, 10)])
    g["4"] = (0.68, [[(0.44, 0.00), (0.44, 1.00), (0.05, 0.32), (0.58, 0.32)]])
    g["5"] = (0.66, [[(0.52, 1.00), (0.10, 1.00), (0.08, 0.54)] + _arc_pts(0.30, 0.31, 0.24, 0.31, 135, -155, 11)])
    g["6"] = (0.68, [_arc_pts(0.32, 0.72, 0.22, 0.28, 35, 180, 6) + _arc_pts(0.31, 0.30, 0.24, 0.30, 180, 540, 14)])
    g["7"] = (0.64, [[(0.06, 1.00), (0.56, 1.00), (0.22, 0.00)]])
    g["8"] = (0.68, [_arc_pts(0.30, 0.76, 0.21, 0.24, 0, 360, 12), _arc_pts(0.30, 0.26, 0.24, 0.26, 0, 360, 12)])
    g["9"] = (0.68, [_arc_pts(0.30, 0.70, 0.24, 0.30, 0, 360, 12) + _arc_pts(0.30, 0.28, 0.24, 0.28, 0, -145, 7)])

    # Chữ hoa A-Z
    g["A"] = (0.74, [[(0.04, 0.00), (0.34, 1.00), (0.64, 0.00)], [(0.14, 0.33), (0.54, 0.33)]])
    g["B"] = (0.70, [
        [(0.08, 0.00), (0.08, 1.00), (0.34, 1.00)] + _arc_pts(0.34, 0.76, 0.21, 0.24, 90, -90, 8) + [(0.08, 0.52)],
        [(0.34, 0.52)] + _arc_pts(0.34, 0.26, 0.23, 0.26, 90, -90, 8) + [(0.08, 0.00)],
    ])
    g["C"] = (0.72, [_arc_pts(0.35, 0.70, 0.27, 0.30, 35, 180, 7) + _arc_pts(0.35, 0.30, 0.27, 0.30, 180, 325, 7)])
    g["D"] = (0.74, [[(0.08, 0.00), (0.08, 1.00), (0.32, 1.00)] + _arc_pts(0.32, 0.50, 0.29, 0.50, 90, -90, 12) + [(0.08, 0.00)]])
    g["E"] = (0.64, [[(0.54, 1.00), (0.08, 1.00), (0.08, 0.00), (0.56, 0.00)], [(0.08, 0.52), (0.46, 0.52)]])
    g["F"] = (0.60, [[(0.54, 1.00), (0.08, 1.00), (0.08, 0.00)], [(0.08, 0.52), (0.46, 0.52)]])
    g["G"] = (0.76, [_arc_pts(0.36, 0.70, 0.28, 0.30, 35, 180, 7) + _arc_pts(0.36, 0.30, 0.28, 0.30, 180, 360, 8) + [(0.64, 0.46), (0.38, 0.46)]])
    g["H"] = (0.74, [[(0.08, 0.00), (0.08, 1.00)], [(0.60, 0.00), (0.60, 1.00)], [(0.08, 0.52), (0.60, 0.52)]])
    g["I"] = (0.34, [[(0.14, 0.00), (0.14, 1.00)]])
    g["J"] = (0.56, [[(0.44, 1.00), (0.44, 0.26)] + _arc_pts(0.25, 0.26, 0.19, 0.26, 0, -165, 8)])
    g["K"] = (0.70, [[(0.08, 0.00), (0.08, 1.00)], [(0.58, 1.00), (0.08, 0.46)], [(0.24, 0.62), (0.60, 0.00)]])
    g["L"] = (0.60, [[(0.08, 1.00), (0.08, 0.00), (0.54, 0.00)]])
    g["M"] = (0.86, [[(0.08, 0.00), (0.08, 1.00), (0.40, 0.18), (0.72, 1.00), (0.72, 0.00)]])
    g["N"] = (0.74, [[(0.08, 0.00), (0.08, 1.00), (0.60, 0.00), (0.60, 1.00)]])
    g["O"] = (0.78, [_arc_pts(0.36, 0.70, 0.28, 0.30, 0, 180, 8) + _arc_pts(0.36, 0.30, 0.28, 0.30, 180, 360, 8) + [(0.64, 0.70)]])
    g["P"] = (0.68, [[(0.08, 0.00), (0.08, 1.00), (0.35, 1.00)] + _arc_pts(0.35, 0.74, 0.22, 0.26, 90, -90, 8) + [(0.08, 0.48)]])
    g["Q"] = (0.78, [
        _arc_pts(0.36, 0.70, 0.28, 0.30, 0, 180, 8) + _arc_pts(0.36, 0.30, 0.28, 0.30, 180, 360, 8) + [(0.64, 0.70)],
        [(0.42, 0.26), (0.66, -0.04)],
    ])
    g["R"] = (0.70, [
        [(0.08, 0.00), (0.08, 1.00), (0.35, 1.00)] + _arc_pts(0.35, 0.74, 0.22, 0.26, 90, -90, 8) + [(0.08, 0.48)],
        [(0.36, 0.48), (0.60, 0.00)],
    ])
    g["S"] = (0.68, [_arc_pts(0.32, 0.75, 0.23, 0.25, 30, 250, 9) + _arc_pts(0.32, 0.26, 0.24, 0.26, 70, -155, 9)])
    g["T"] = (0.64, [[(0.04, 1.00), (0.58, 1.00)], [(0.31, 1.00), (0.31, 0.00)]])
    g["U"] = (0.74, [[(0.08, 1.00), (0.08, 0.28)] + _arc_pts(0.34, 0.28, 0.26, 0.28, 180, 360, 9) + [(0.60, 1.00)]])
    g["V"] = (0.70, [[(0.04, 1.00), (0.33, 0.00), (0.62, 1.00)]])
    g["W"] = (0.94, [[(0.04, 1.00), (0.21, 0.00), (0.44, 0.72), (0.67, 0.00), (0.84, 1.00)]])
    g["X"] = (0.70, [[(0.06, 1.00), (0.60, 0.00)], [(0.60, 1.00), (0.06, 0.00)]])
    g["Y"] = (0.68, [[(0.04, 1.00), (0.32, 0.48), (0.60, 1.00)], [(0.32, 0.48), (0.32, 0.00)]])
    g["Z"] = (0.66, [[(0.06, 1.00), (0.58, 1.00), (0.06, 0.00), (0.58, 0.00)]])

    # Chữ thường a-z (x-height = 0.70, chân chữ descender = -0.26)
    g["a"] = (0.60, [_arc_pts(0.28, 0.35, 0.21, 0.35, 0, 360, 12), [(0.49, 0.70), (0.49, 0.00)]])
    g["b"] = (0.60, [[(0.08, 1.00), (0.08, 0.00)], _arc_pts(0.29, 0.35, 0.21, 0.35, 0, 360, 12)])
    g["c"] = (0.56, [_arc_pts(0.29, 0.35, 0.21, 0.35, 40, 320, 10)])
    g["d"] = (0.60, [_arc_pts(0.28, 0.35, 0.21, 0.35, 0, 360, 12), [(0.49, 1.00), (0.49, 0.00)]])
    g["e"] = (0.58, [[(0.07, 0.35), (0.49, 0.35)] + _arc_pts(0.28, 0.35, 0.21, 0.35, 0, 325, 11)])
    g["f"] = (0.38, [_arc_pts(0.26, 0.84, 0.12, 0.16, 45, 180, 5) + [(0.14, 0.00)], [(0.04, 0.68), (0.30, 0.68)]])
    g["g"] = (0.60, [
        _arc_pts(0.28, 0.35, 0.21, 0.35, 0, 360, 12),
        [(0.49, 0.70), (0.49, -0.08)] + _arc_pts(0.28, -0.08, 0.21, 0.18, 0, -160, 7),
    ])
    g["h"] = (0.58, [[(0.08, 1.00), (0.08, 0.00)], [(0.08, 0.48)] + _arc_pts(0.28, 0.48, 0.20, 0.22, 180, 0, 7) + [(0.48, 0.00)]])
    g["i"] = (0.28, [[(0.11, 0.00), (0.11, 0.70)], [(0.11, 0.92), (0.11, 0.98)]])
    g["j"] = (0.32, [[(0.18, 0.70), (0.18, -0.10)] + _arc_pts(0.08, -0.10, 0.10, 0.14, 0, -150, 5), [(0.18, 0.92), (0.18, 0.98)]])
    g["k"] = (0.54, [[(0.08, 1.00), (0.08, 0.00)], [(0.46, 0.70), (0.08, 0.32)], [(0.20, 0.44), (0.48, 0.00)]])
    g["l"] = (0.28, [[(0.11, 1.00), (0.11, 0.00)]])
    g["m"] = (0.86, [
        [(0.07, 0.00), (0.07, 0.70)],
        [(0.07, 0.50)] + _arc_pts(0.24, 0.50, 0.17, 0.20, 180, 0, 6) + [(0.41, 0.00)],
        [(0.41, 0.50)] + _arc_pts(0.58, 0.50, 0.17, 0.20, 180, 0, 6) + [(0.75, 0.00)],
    ])
    g["n"] = (0.58, [[(0.08, 0.00), (0.08, 0.70)], [(0.08, 0.48)] + _arc_pts(0.28, 0.48, 0.20, 0.22, 180, 0, 7) + [(0.48, 0.00)]])
    g["o"] = (0.60, [_arc_pts(0.28, 0.35, 0.21, 0.35, 0, 360, 12)])
    g["p"] = (0.60, [[(0.08, 0.70), (0.08, -0.26)], _arc_pts(0.29, 0.35, 0.21, 0.35, 0, 360, 12)])
    g["q"] = (0.60, [_arc_pts(0.28, 0.35, 0.21, 0.35, 0, 360, 12), [(0.49, 0.70), (0.49, -0.26)]])
    g["r"] = (0.40, [[(0.08, 0.00), (0.08, 0.70)], [(0.08, 0.48)] + _arc_pts(0.24, 0.50, 0.14, 0.20, 180, 45, 5)])
    g["s"] = (0.52, [_arc_pts(0.24, 0.53, 0.17, 0.17, 25, 255, 7) + _arc_pts(0.24, 0.18, 0.18, 0.18, 75, -155, 7)])
    g["t"] = (0.38, [[(0.16, 0.92), (0.16, 0.00)], [(0.04, 0.70), (0.30, 0.70)]])
    g["u"] = (0.58, [[(0.08, 0.70), (0.08, 0.22)] + _arc_pts(0.28, 0.22, 0.20, 0.22, 180, 360, 7), [(0.48, 0.70), (0.48, 0.00)]])
    g["v"] = (0.54, [[(0.04, 0.70), (0.25, 0.00), (0.46, 0.70)]])
    g["w"] = (0.78, [[(0.04, 0.70), (0.17, 0.00), (0.36, 0.54), (0.55, 0.00), (0.68, 0.70)]])
    g["x"] = (0.52, [[(0.05, 0.70), (0.45, 0.00)], [(0.45, 0.70), (0.05, 0.00)]])
    g["y"] = (0.54, [[(0.04, 0.70), (0.25, 0.00)], [(0.46, 0.70), (0.14, -0.26)]])
    g["z"] = (0.52, [[(0.05, 0.70), (0.45, 0.70), (0.05, 0.00), (0.45, 0.00)]])

    # Dấu câu & Ký hiệu bản vẽ cơ khí (Ø, ø, ⌀, ±, °, ×, ≤, ≥, µ, ⊥, ∥, ⌖, ⌴, ⌵, ↧, △, □)
    g["."] = (0.28, [_arc_pts(0.11, 0.05, 0.04, 0.05, 0, 360, 6)])
    g[","] = (0.28, [[(0.13, 0.12), (0.07, -0.14)]])
    g[":"] = (0.28, [_arc_pts(0.11, 0.58, 0.04, 0.05, 0, 360, 6), _arc_pts(0.11, 0.08, 0.04, 0.05, 0, 360, 6)])
    g[";"] = (0.28, [_arc_pts(0.11, 0.58, 0.04, 0.05, 0, 360, 6), [(0.13, 0.12), (0.07, -0.14)]])
    g["-"] = (0.46, [[(0.06, 0.42), (0.36, 0.42)]])
    g["_"] = (0.56, [[(0.02, -0.05), (0.50, -0.05)]])
    g["+"] = (0.64, [[(0.06, 0.46), (0.52, 0.46)], [(0.29, 0.18), (0.29, 0.74)]])
    g["="] = (0.64, [[(0.06, 0.60), (0.52, 0.60)], [(0.06, 0.32), (0.52, 0.32)]])
    g["/"] = (0.44, [[(0.04, -0.05), (0.36, 1.02)]])
    g["\\"] = (0.44, [[(0.04, 1.02), (0.36, -0.05)]])
    g["("] = (0.38, [_arc_pts(0.28, 0.48, 0.16, 0.56, 115, 245, 8)])
    g[")"] = (0.38, [_arc_pts(0.06, 0.48, 0.16, 0.56, 65, -65, 8)])
    g["["] = (0.38, [[(0.26, 1.02), (0.08, 1.02), (0.08, -0.06), (0.26, -0.06)]])
    g["]"] = (0.38, [[(0.06, 1.02), (0.24, 1.02), (0.24, -0.06), (0.06, -0.06)]])
    g["<"] = (0.58, [[(0.46, 0.78), (0.08, 0.46), (0.46, 0.14)]])
    g[">"] = (0.58, [[(0.08, 0.78), (0.46, 0.46), (0.08, 0.14)]])
    g["'"] = (0.24, [[(0.10, 1.00), (0.10, 0.72)]])
    g['"'] = (0.38, [[(0.08, 1.00), (0.08, 0.72)], [(0.24, 1.00), (0.24, 0.72)]])
    g["%"] = (0.78, [
        [(0.10, 0.00), (0.62, 1.00)],
        _arc_pts(0.18, 0.82, 0.10, 0.14, 0, 360, 8),
        _arc_pts(0.54, 0.18, 0.10, 0.14, 0, 360, 8),
    ])
    g["Ø"] = (0.82, [_arc_pts(0.38, 0.50, 0.30, 0.38, 0, 360, 14), [(0.06, 0.02), (0.70, 0.98)]])
    g["ø"] = (0.62, [_arc_pts(0.28, 0.35, 0.21, 0.35, 0, 360, 12), [(0.05, -0.02), (0.51, 0.72)]])
    g["⌀"] = g["Ø"]
    g["±"] = (0.70, [
        [(0.08, 0.64), (0.56, 0.64)],
        [(0.32, 0.36), (0.32, 0.92)],
        [(0.08, 0.12), (0.56, 0.12)],
    ])
    g["°"] = (0.38, [_arc_pts(0.16, 0.84, 0.11, 0.13, 0, 360, 8)])
    g["×"] = (0.64, [[(0.08, 0.18), (0.52, 0.74)], [(0.52, 0.18), (0.08, 0.74)]])
    g["≤"] = (0.64, [[(0.50, 0.84), (0.08, 0.54), (0.50, 0.24)], [(0.08, 0.08), (0.50, 0.08)]])
    g["≥"] = (0.64, [[(0.08, 0.84), (0.50, 0.54), (0.08, 0.24)], [(0.08, 0.08), (0.50, 0.08)]])
    g["µ"] = (0.60, [[(0.08, -0.24), (0.08, 0.70)], [(0.08, 0.22)] + _arc_pts(0.28, 0.22, 0.20, 0.22, 180, 360, 7), [(0.48, 0.70), (0.48, 0.00)]])
    g["⊥"] = (0.68, [[(0.06, 0.00), (0.58, 0.00)], [(0.32, 0.00), (0.32, 0.92)]])
    g["∥"] = (0.54, [[(0.12, 0.00), (0.12, 0.96)], [(0.34, 0.00), (0.34, 0.96)]])
    g["⌖"] = (0.78, [_arc_pts(0.36, 0.50, 0.24, 0.28, 0, 360, 12), [(0.04, 0.50), (0.68, 0.50)], [(0.36, 0.12), (0.36, 0.88)]])
    g["⌴"] = (0.72, [[(0.06, 0.88), (0.06, 0.04), (0.58, 0.04), (0.58, 0.88)]])
    g["⌵"] = (0.72, [[(0.04, 0.88), (0.32, 0.04), (0.60, 0.88)]])
    g["↧"] = (0.68, [[(0.06, 0.88), (0.58, 0.88)], [(0.32, 0.88), (0.32, 0.04)], [(0.16, 0.28), (0.32, 0.04), (0.48, 0.28)]])
    g["△"] = (0.72, [[(0.06, 0.04), (0.34, 0.92), (0.62, 0.04), (0.06, 0.04)]])
    g["□"] = (0.72, [[(0.08, 0.06), (0.58, 0.06), (0.58, 0.86), (0.08, 0.86), (0.08, 0.06)]])
    return g


_CAD_FONT = _build_cad_font()

_SW_SYM_MAP = {
    "<MOD-DIAM>": "Ø",
    "<MOD-PM>": "±",
    "<MOD-DEG>": "°",
    "<MOD-PLUS>": "+",
    "<MOD-MINUS>": "-",
    "<MOD-LE>": "≤",
    "<MOD-GE>": "≥",
    "<MOD-MICRO>": "µ",
    "<MOD-PERP>": "⊥",
    "<MOD-PARA>": "∥",
    "<MOD-POS>": "⌖",
    "<MOD-CBORE>": "⌴",
    "<MOD-CSINK>": "⌵",
    "<MOD-DEPTH>": "↧",
    "%%C": "Ø",
    "%%c": "Ø",
    "%%P": "±",
    "%%p": "±",
    "%%D": "°",
    "%%d": "°",
}


def normalize_sw_text(text: str) -> str:
    """Chuyển đổi các mã ký hiệu nội bộ của SolidWorks (<MOD-DIAM>, <MOD-PM>, ...) sang Unicode."""
    for k, v in _SW_SYM_MAP.items():
        if k in text:
            text = text.replace(k, v)
    return re.sub(r"<[A-Z0-9_-]+>", "", text)


def _text_to_polylines(text: str, x0_mm: float, y0_mm: float, h_mm: float,
                       vertical: bool = False) -> list[list[tuple[float, float, float]]]:
    """Chuyển chuỗi văn bản thành danh sách các polyline 3D (Z=0, đơn vị mm) với font CAD nét mượt."""
    text = normalize_sw_text(text)
    out: list[list[tuple[float, float, float]]] = []
    cx = 0.0
    for ch in text:
        if ch == " ":
            cx += h_mm * 0.36
            continue
        glyph = _CAD_FONT.get(ch) or _CAD_FONT.get(ch.upper())
        if not glyph:
            cx += h_mm * 0.50
            continue
        adv, strokes = glyph
        for st in strokes:
            pts: list[tuple[float, float, float]] = []
            for gx, gy in st:
                lx = cx + gx * h_mm
                ly = gy * h_mm
                if vertical:
                    px, py = x0_mm - ly, y0_mm + lx
                else:
                    px, py = x0_mm + lx, y0_mm + ly
                pts.append((round(px, 4), round(py, 4), 0.0))
            if len(pts) >= 2:
                out.append(pts)
        cx += adv * h_mm
    return out


# --------------------------------------------------------------------------- #
# Giải mã Container GContainer & Trích xuất màu sắc / Bản vẽ nhiều tờ (.SLDDRW)
# --------------------------------------------------------------------------- #
_BLOCK_MARKER = b"\x14\x00\x06\x00\x08\x00"
_ENTRY_HDR = struct.Struct("<IHHIIIII")          # 28 byte


def _swap_nibbles(b: bytes) -> bytes:
    return bytes(((x >> 4) | ((x & 0x0F) << 4)) for x in b)


def unpack_sld_gcontainer(src: Path) -> dict[str, bytes]:
    """Giải nén container SolidWorks 2015+ bằng thuần Python.

    Lưu ý: 4 byte đầu file KHÔNG phải magic cố định (mỗi file một giá trị khác nhau) và phần
    header trước entry đầu tiên dài 18-20 byte tuỳ file, nên không được dựa vào chúng. Điểm neo
    đáng tin cậy là dấu hiệu 14 00 06 00 08 00 (entry bắt đầu 2 byte trước dấu hiệu)."""
    data = src.read_bytes()
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("File SolidWorks cũ (trước 2015, định dạng OLE2) chưa được hỗ trợ")
    first = data.find(_BLOCK_MARKER, 0, 256)
    if first < 2:
        raise ValueError("Không phải container SolidWorks 2015+ (không thấy dấu hiệu khối 14 00 06 00 08 00)")
    streams: dict[str, bytes] = {}
    pos = first - 2
    while pos + _ENTRY_HDR.size <= len(data):
        u0, ver1, ver2, ts, crc, csize, usize, name_len = _ENTRY_HDR.unpack_from(data, pos)
        if ver1 != 6 or ver2 != 8 or name_len > 512 or pos + 28 + name_len > len(data):
            break
        name = _swap_nibbles(data[pos + 28 : pos + 28 + name_len]).decode("utf-8", errors="replace")
        body = pos + 28 + name_len
        verified = False
        if "\x00" not in name and csize > 0 and body + csize <= len(data):
            try:
                dec = zlib.decompress(data[body : body + csize], -15)
                if len(dec) == usize and (crc == 0 or zlib.crc32(dec) == crc):
                    streams[name] = dec
                    verified = True
            except Exception:
                pass
        m = data.find(_BLOCK_MARKER, body + (csize if verified else 0))
        if m == -1:
            break
        pos = m - 2
    return streams


def extract_sld_colors(streams: dict[str, bytes]) -> list[tuple[float, float, float]]:
    """Trích xuất danh sách màu RGB (0.0..1.0) của các Body / Vật liệu từ Contents/VBLists và DisplayLists."""
    colors: list[tuple[float, float, float]] = []
    for sname in ("Contents/VBLists", "Contents/DisplayLists", "Contents/Definition"):
        buf = streams.get(sname, b"")
        if not buf:
            continue
        # 1. Tìm màu trong uoBodyPropInfo_c (tag \x0e\x80 + 4 byte 0 + 16 byte 0xFF + R G B 00)
        pos = 0
        while True:
            idx = buf.find(b"uoBodyPropInfo_c", pos)
            if idx == -1:
                break
            tag = buf.find(b"\x0e\x80\x00\x00\x00\x00" + b"\xff" * 16, idx, idx + 120)
            if tag != -1 and tag + 26 <= len(buf):
                r, g, b = buf[tag + 22], buf[tag + 23], buf[tag + 24]
                if (r, g, b) not in ((0, 0, 0), (255, 255, 255)):
                    col = (round(r / 255.0, 4), round(g / 255.0, 4), round(b / 255.0, 4))
                    if col not in colors:
                        colors.append(col)
            pos = idx + 16
        # 2. Tìm màu trong moVisualProperties_c (offset +36 sau tên lớp là R G B 00)
        pos = 0
        while True:
            idx = buf.find(b"moVisualProperties_c", pos)
            if idx == -1:
                break
            c_off = idx + len(b"moVisualProperties_c") + 36
            if c_off + 4 <= len(buf):
                r, g, b, a = buf[c_off : c_off + 4]
                if a == 0 and (r, g, b) not in ((0, 0, 0), (255, 255, 255)):
                    col = (round(r / 255.0, 4), round(g / 255.0, 4), round(b / 255.0, 4))
                    if col not in colors:
                        colors.append(col)
            pos = idx + 20
    return colors


def inject_step_ap214_colors(step_path: Path, sld_src: Path) -> bool:
    """Nếu file STEP xuất từ .SLDPRT/.SLDASM chưa có thông tin màu (COLOUR_RGB), tự động trích xuất
    màu vật liệu/body từ file SolidWorks gốc và gắn STYLED_ITEM chuẩn STEP AP214 vào các khối 3D."""
    try:
        if not step_path.exists() or step_path.stat().st_size == 0:
            return False
        text = step_path.read_text(encoding="utf-8", errors="ignore")
        if "STYLED_ITEM(" in text and "COLOUR_RGB(" in text:
            return False
        streams = unpack_sld_gcontainer(sld_src)
        colors = extract_sld_colors(streams)
        if not colors:
            # Thêm tìm kiếm màu từ các part nhúng ImportedComp/* nếu là Assembly
            for k, v in streams.items():
                if k.startswith("ImportedComp/"):
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".sldprt", delete=False) as tf:
                            tf.write(v)
                            tf_path = Path(tf.name)
                        sub_streams = unpack_sld_gcontainer(tf_path)
                        tf_path.unlink(missing_ok=True)
                        for c in extract_sld_colors(sub_streams):
                            if c not in colors:
                                colors.append(c)
                    except Exception:
                        pass
        if not colors:
            colors = [(0.76, 0.78, 0.80)]  # Màu kim loại thép phay mặc định của SolidWorks

        # Tìm các MANIFOLD_SOLID_BREP hoặc SHELL_BASED_SURFACE_MODEL và GEOMETRIC_REPRESENTATION_CONTEXT
        solids = re.findall(r"#(\d+)\s*=\s*(?:MANIFOLD_SOLID_BREP|SHELL_BASED_SURFACE_MODEL|BREP_WITH_VOIDS)\s*\(", text)
        ctx_m = re.search(r"#(\d+)\s*=\s*\(\s*GEOMETRIC_REPRESENTATION_CONTEXT\s*\(\s*3\s*\)", text)
        if not solids or not ctx_m:
            return False
        ctx_id = int(ctx_m.group(1))
        all_ids = [int(x) for x in re.findall(r"#(\d+)\s*=", text)]
        max_id = max(all_ids) if all_ids else 1000

        extra_lines: list[str] = []

        def new_ent(body: str) -> int:
            nonlocal max_id
            max_id += 1
            extra_lines.append(f"#{max_id} = {body};")
            return max_id

        styled_ids: list[int] = []
        for idx_s, solid_id_str in enumerate(solids):
            r, g, b = colors[idx_s % len(colors)]
            col_id = new_ent(f"COLOUR_RGB('',{r:.4f},{g:.4f},{b:.4f})")
            fas_col = new_ent(f"FILL_AREA_STYLE_COLOUR('',#{col_id})")
            fas = new_ent(f"FILL_AREA_STYLE('',(#{fas_col}))")
            ss_fill = new_ent(f"SURFACE_STYLE_FILL_AREA(#{fas})")
            ss_side = new_ent(f"SURFACE_SIDE_STYLE('',(#{ss_fill}))")
            ss_usage = new_ent(f"SURFACE_STYLE_USAGE(.BOTH.,#{ss_side})")
            psa = new_ent(f"PRESENTATION_STYLE_ASSIGNMENT((#{ss_usage}))")
            st_item = new_ent(f"STYLED_ITEM('',(#{psa}),#{solid_id_str})")
            styled_ids.append(st_item)

        s_refs = ",".join(f"#{i}" for i in styled_ids)
        new_ent(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({s_refs}),#{ctx_id})")

        endsec_idx = text.rfind("ENDSEC;")
        if endsec_idx == -1:
            return False
        new_text = text[:endsec_idx] + "\n".join(extra_lines) + "\n" + text[endsec_idx:]
        step_path.write_text(new_text, encoding="utf-8")
        return True
    except Exception:
        return False


def parse_sheet_names(streams: dict[str, bytes]) -> list[str]:
    """Giải mã danh sách tên các tờ bản vẽ từ luồng SheetPreviews/SheetNames hoặc Images/Sheet_*."""
    sn = streams.get("SheetPreviews/SheetNames", b"")
    names: list[str] = []
    if len(sn) >= 2:
        pos = 2
        while pos < len(sn):
            idx = sn.find(b"\xff\xfe\xff", pos)
            if idx == -1 or idx + 4 > len(sn):
                break
            slen = sn[idx + 3]
            sstart = idx + 4
            if slen == 0xFF and idx + 6 <= len(sn):
                slen = struct.unpack_from("<H", sn, idx + 4)[0]
                sstart = idx + 6
            if sstart + slen * 2 <= len(sn):
                name = sn[sstart : sstart + slen * 2].decode("utf-16le", errors="replace").strip()
                if name:
                    names.append(name)
                pos = sstart + slen * 2
            else:
                break
    if not names:
        sheet_imgs = sorted(k for k in streams if k.startswith("Images/Sheet_"))
        for idx in range(max(1, len(sheet_imgs))):
            names.append(f"Sheet{idx + 1}")
    return names


@dataclass
class SldDrwSheet:
    """Dữ liệu hình học 2D của 1 tờ bản vẽ (đã chia sẵn thành 4 Layer: Khung, Hình chiếu, Kích thước, Chữ)."""
    index: int
    name: str
    width_mm: float = 420.0
    height_mm: float = 297.0
    offset_x_mm: float = 0.0
    # Layer 1: 01_Khung_Ban_Ve (BORDER)
    border_lines_mm: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = field(default_factory=list)
    border_circles_mm: list[tuple[float, float, float]] = field(default_factory=list)
    border_arcs_mm: list[list[tuple[float, float, float]]] = field(default_factory=list)
    # Layer 2: 02_Hinh_Chieu (VIEWS)
    view_polylines_2d_mm: list[list[tuple[float, float, float]]] = field(default_factory=list)
    n_views: int = 0
    # Layer 3: 03_Kich_Thuoc (DIMENSIONS)
    dim_lines_mm: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = field(default_factory=list)
    dim_tris_mm: list[list[tuple[float, float, float]]] = field(default_factory=list)
    dim_circles_mm: list[tuple[float, float, float]] = field(default_factory=list)
    dim_arcs_mm: list[list[tuple[float, float, float]]] = field(default_factory=list)
    dim_texts_mm: list[tuple[float, float, float, bool, str]] = field(default_factory=list)
    # Layer 4: 04_Chu_Ghi_Chu (TEXT_NOTES)
    note_texts_mm: list[tuple[float, float, float, bool, str]] = field(default_factory=list)


@dataclass
class SldDrwData:
    sheets: list[SldDrwSheet]
    # Tương thích ngược với thuộc tính tổng hợp
    sheet_lines_mm: list[tuple[tuple[float, float, float], tuple[float, float, float]]]
    sheet_tris_mm: list[list[tuple[float, float, float]]]
    sheet_circles_mm: list[tuple[float, float, float]]
    texts_mm: list[tuple[float, float, float, bool, str]]
    view_polylines_2d_mm: list[list[tuple[float, float, float]]]
    model_polylines_3d_mm: list[list[tuple[float, float, float]]]
    model_faces_3d_mm: list[tuple[tuple[float, float, float], list[tuple[float, float, float]]]]
    model_color_rgb: tuple[float, float, float]
    referenced_paths: list[str]
    n_views: int = 0
    n_3d_faces: int = 0


def parse_slddrw_geometry(src: Path, sheet_filter: int | None = None) -> SldDrwData:
    """Trích xuất toàn bộ hình học 2D (hỗ trợ bản vẽ nhiều tờ, chia 4 Layer: Khung, Hình chiếu,
    Kích thước, Chữ) và mô hình 3D (mặt/cạnh + màu vật liệu) từ file .SLDDRW."""
    streams = unpack_sld_gcontainer(src)
    dl = streams.get("Contents/DisplayLists", b"")
    vb = streams.get("Contents/VBLists", b"")
    xml2 = streams.get("swXmlContents/xmlstream-2", b"").decode("utf-8", errors="ignore")

    referenced_paths: list[str] = []
    for m in re.finditer(r'sw(?:Imported)?Path="([^"]+)"', xml2):
        p_str = m.group(1)
        if p_str not in referenced_paths:
            referenced_paths.append(p_str)

    colors = extract_sld_colors(streams)
    model_color_rgb = colors[0] if colors else (0.76, 0.78, 0.80)

    sheet_names = parse_sheet_names(streams)
    n_declared_sheets = max(1, len(sheet_names))

    # 1. Trích xuất các bucket cạnh 3D (uiViewBucket_c) từ VBLists kèm vector pháp tuyến chiếu
    tess_start = vb.find(b"uoTemp")
    if tess_start == -1:
        tess_start = vb.find(b"moAmbientLight_c")
    vb_head = vb[:tess_start] if tess_start != -1 else vb

    bucket_marker = b"\x01\x80\x00\x00\x00\x00\x00\x00\x00\x00"
    bucket_starts: list[int] = [0]
    bpos = 24
    while True:
        idx = vb_head.find(bucket_marker, bpos)
        if idx == -1:
            break
        bucket_starts.append(idx)
        bpos = idx + 10

    buckets: list[list[list[tuple[float, float, float]]]] = []
    bucket_normals: list[tuple[float, float, float] | None] = []
    model_polylines_3d_mm: list[list[tuple[float, float, float]]] = []
    seen_3d_edges: set[tuple] = set()

    for bi, b_start in enumerate(bucket_starts):
        b_end = bucket_starts[bi + 1] if bi + 1 < len(bucket_starts) else len(vb_head)
        chunk = vb_head[b_start:b_end]
        # Đọc vector pháp tuyến góc nhìn 3D của uiViewBucket_c
        n_off = 0x18 if b_start == 0 else 2
        b_norm: tuple[float, float, float] | None = None
        if n_off + 24 <= len(chunk):
            nx, ny, nz = struct.unpack_from("<3d", chunk, n_off)
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            if 0.9 <= ln <= 1.1:
                b_norm = (nx / ln, ny / ln, nz / ln)

        b_curves: list[list[tuple[float, float, float]]] = []
        i = 0
        while i < len(chunk) - 36:
            one, flags, npts = struct.unpack_from("<III", chunk, i)
            if one == 1 and (0x100 <= flags <= 0x7FF) and 2 <= npts <= 2000:
                end_pts = i + 12 + npts * 24
                if end_pts <= len(chunk):
                    pts = struct.unpack_from(f"<{npts * 3}d", chunk, i + 12)
                    if all(abs(x) < 50.0 and not math.isnan(x) for x in pts):
                        coords_m = [(pts[3 * k], pts[3 * k + 1], pts[3 * k + 2]) for k in range(npts)]
                        b_curves.append(coords_m)
                        coords_mm = [
                            (round(x * 1000.0, 4), round(y * 1000.0, 4), round(z * 1000.0, 4))
                            for x, y, z in coords_m
                        ]
                        key = (coords_mm[0], coords_mm[-1], len(coords_mm))
                        rkey = (coords_mm[-1], coords_mm[0], len(coords_mm))
                        if key not in seen_3d_edges and rkey not in seen_3d_edges:
                            seen_3d_edges.add(key)
                            model_polylines_3d_mm.append(coords_mm)
                        i = end_pts + 80
                        continue
            i += 1
        if b_curves:
            buckets.append(b_curves)
            bucket_normals.append(b_norm)

    # 2. Tìm vị trí các Drawing Views trong DisplayLists trước để định vị ranh giới giữa các Sheet
    view_hdr = bytes.fromhex(
        "3c00000009000000010000000100000000000000000000000000000080bf050000000000000000000000"
    )
    raw_views: list[tuple[int, tuple[float, ...], tuple[float, float, float], float, tuple[float, float, float]]] = []
    pos = 0
    while True:
        idx = dl.find(view_hdr, pos)
        if idx == -1:
            break
        p = idx + len(view_hdr)
        if p + 60 > len(dl):
            break
        if dl[p] == 0:
            r = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
            p += 1
        else:
            p += 1
            if p + 72 + 58 > len(dl):
                break
            r = struct.unpack_from("<9d", dl, p)
            p += 72
        ox, oy, oz, sc = struct.unpack_from("<4d", dl, p)
        p += 32 + 2
        cx, cy, cz = struct.unpack_from("<3d", dl, p)
        if 1e-4 <= sc <= 1000.0 and 0.0 < abs(cx) < 10.0 and not math.isnan(cy):
            raw_views.append((idx, r, (ox, oy, oz), sc, (cx, cy, cz)))
        pos = p + 24

    # 3. Quét DisplayLists và tự động chia theo từng tờ (Multi-Sheet) + chia Layer (Border vs Dimension)
    # Trong DisplayLists của SolidWorks, mỗi Sheet được lưu theo thứ tự:
    #   [Khung bản vẽ & chữ khung tên ở z == 0] -> [Các Drawing Views & Kích thước ở z != 0].
    # Khi file có nhiều tờ (n_declared_sheets > 1), sau khi đã đi qua ít nhất 1 Drawing View của tờ k
    # mà gặp lại một cụm >= 8 đường thẳng khung giấy ở z == 0, đó chính là điểm bắt đầu của tờ k + 1.
    sheets: list[SldDrwSheet] = [
        SldDrwSheet(index=k + 1, name=sheet_names[k] if k < len(sheet_names) else f"Sheet{k + 1}")
        for k in range(n_declared_sheets)
    ]

    # Tìm các điểm chia sheet (sheet_split_offsets) trong dl nếu có > 1 tờ
    sheet_split_offsets: list[int] = [0]
    if n_declared_sheets > 1 and raw_views:
        view_offsets = [v[0] for v in raw_views]
        cur_v_idx = 0
        i = 0
        z0_streak = 0
        first_z0_pos = 0
        while i < len(dl) - 56 and len(sheet_split_offsets) < n_declared_sheets:
            sz, op = struct.unpack_from("<II", dl, i)
            if sz == 0x50 and op == 4:
                pts = struct.unpack_from("<6d", dl, i + 8)
                if all(abs(x) < 10.0 and not math.isnan(x) for x in pts):
                    is_z0 = abs(pts[2]) <= 1e-6 and abs(pts[5]) <= 1e-6
                    passed_view = cur_v_idx < len(view_offsets) and i > view_offsets[cur_v_idx]
                    if is_z0 and passed_view:
                        if z0_streak == 0:
                            first_z0_pos = i
                        z0_streak += 1
                        if z0_streak >= 8:
                            sheet_split_offsets.append(first_z0_pos)
                            while cur_v_idx < len(view_offsets) and view_offsets[cur_v_idx] < first_z0_pos:
                                cur_v_idx += 1
                            z0_streak = 0
                    else:
                        z0_streak = 0
                    i += 56
                    continue
            i += 1

    def _sheet_idx_for_offset(byte_off: int) -> int:
        s_idx = 0
        for k, sp in enumerate(sheet_split_offsets):
            if byte_off >= sp:
                s_idx = k
        return min(s_idx, len(sheets) - 1)

    seen_lines_per_sheet: list[set[tuple]] = [set() for _ in sheets]

    i = 0
    while i < len(dl) - 56:
        sz, op = struct.unpack_from("<II", dl, i)
        if sz == 0x50 and op == 4 and i + 56 <= len(dl):
            pts = struct.unpack_from("<6d", dl, i + 8)
            if all(abs(x) < 10.0 and not math.isnan(x) for x in pts):
                p0 = (round(pts[0] * 1000.0, 4), round(pts[1] * 1000.0, 4), 0.0)
                p1 = (round(pts[3] * 1000.0, 4), round(pts[4] * 1000.0, 4), 0.0)
                if p0 != p1:
                    s_idx = _sheet_idx_for_offset(i)
                    lkey = (p0, p1) if p0 < p1 else (p1, p0)
                    if lkey not in seen_lines_per_sheet[s_idx]:
                        seen_lines_per_sheet[s_idx].add(lkey)
                        is_dim = abs(pts[2]) > 1e-6 or abs(pts[5]) > 1e-6
                        if is_dim:
                            sheets[s_idx].dim_lines_mm.append((p0, p1))
                        else:
                            sheets[s_idx].border_lines_mm.append((p0, p1))
                i += 56
                continue
        elif sz == 0x78 and op == 6 and i + 88 <= len(dl):
            u1, npts = struct.unpack_from("<II", dl, i + 8)
            if npts == 3:
                pts = struct.unpack_from("<9d", dl, i + 16)
                if all(abs(x) < 10.0 and not math.isnan(x) for x in pts):
                    s_idx = _sheet_idx_for_offset(i)
                    tri = [
                        (round(pts[0] * 1000.0, 4), round(pts[1] * 1000.0, 4), 0.0),
                        (round(pts[3] * 1000.0, 4), round(pts[4] * 1000.0, 4), 0.0),
                        (round(pts[6] * 1000.0, 4), round(pts[7] * 1000.0, 4), 0.0),
                    ]
                    sheets[s_idx].dim_tris_mm.append(tri)
                    i += 88
                    continue
        elif sz == 0x80 and op == 2 and i + 80 <= len(dl):
            pts = struct.unpack_from("<9d", dl, i + 8)
            if all(abs(x) < 10.0 and not math.isnan(x) for x in pts):
                s_idx = _sheet_idx_for_offset(i)
                x0, y0, z0 = pts[0] * 1000.0, pts[1] * 1000.0, pts[2]
                x1, y1, z1 = pts[3] * 1000.0, pts[4] * 1000.0, pts[5]
                xc, yc, zc = pts[6] * 1000.0, pts[7] * 1000.0, pts[8]
                rad = math.hypot(x0 - xc, y0 - yc)
                if rad > 1e-3:
                    is_dim = abs(z0) > 1e-6 or abs(z1) > 1e-6 or abs(zc) > 1e-6
                    # Kiểm tra đường tròn kín hay cung tròn (arc)
                    if math.hypot(x1 - x0, y1 - y0) <= 0.05:
                        c_item = (round(xc, 4), round(yc, 4), round(rad, 4))
                        if is_dim:
                            sheets[s_idx].dim_circles_mm.append(c_item)
                        else:
                            sheets[s_idx].border_circles_mm.append(c_item)
                    else:
                        a0 = math.degrees(math.atan2(y0 - yc, x0 - xc))
                        a1 = math.degrees(math.atan2(y1 - yc, x1 - xc))
                        if a1 < a0:
                            a1 += 360.0
                        if a1 - a0 > 180.0:
                            a0, a1 = a1, a0 + 360.0
                        arc_2d = _arc_pts(xc, yc, rad, rad, a0, a1, 16)
                        arc_3d = [(p[0], p[1], 0.0) for p in arc_2d]
                        if is_dim:
                            sheets[s_idx].dim_arcs_mm.append(arc_3d)
                        else:
                            sheets[s_idx].border_arcs_mm.append(arc_3d)
                i += 80
                continue
        i += 1

    # Trích xuất chữ (opcode 0x12) kèm cỡ chữ chính xác (op == 0x0a)
    pos = 0
    while pos < len(dl) - 64:
        if dl[pos : pos + 3] == b"\xff\xfe\xff" and pos >= 48:
            sz, op = struct.unpack_from("<II", dl, pos - 48)
            if op == 0x12 and 0x50 <= sz <= 0x1000:
                x, y, z, dx, dy = struct.unpack_from("<5d", dl, pos - 40)
                slen = dl[pos + 3]
                sstart = pos + 4
                if slen == 0xFF and pos + 6 <= len(dl):
                    slen = struct.unpack_from("<H", dl, pos + 4)[0]
                    sstart = pos + 6
                if sstart + slen * 2 <= len(dl):
                    raw_txt = dl[sstart : sstart + slen * 2].decode("utf-16le", errors="replace")
                    txt = normalize_sw_text(raw_txt)
                    # Tìm header font (op == 0x0a) trong phạm vi 2000 byte phía trước (hỗ trợ cả đoạn văn nhiều dòng)
                    f_idx = dl.rfind(b"\x6c\x00\x00\x00\x0a\x00\x00\x00", max(0, pos - 2000), pos)
                    h_mm = 2.0
                    if f_idx != -1 and f_idx + 36 <= len(dl):
                        d1, pt_sz = struct.unpack_from("<dI", dl, f_idx + 8)
                        if 0.0004 <= d1 <= 0.05:
                            h_mm = d1 * 1000.0 * 0.68
                        elif 1 <= pt_sz <= 72:
                            h_mm = pt_sz * 0.23
                        else:
                            h_val = struct.unpack_from("<d", dl, f_idx + 24)[0]
                            if 0.0005 <= h_val <= 0.05:
                                h_mm = h_val * 1000.0 * 0.72
                    if abs(x) < 10.0 and abs(y) < 10.0 and txt.strip():
                        s_idx = _sheet_idx_for_offset(pos)
                        vertical = abs(dx) > 1e10
                        t_entry = (
                            round(x * 1000.0, 4),
                            round(y * 1000.0, 4),
                            round(h_mm, 4),
                            vertical,
                            txt,
                        )
                        if abs(z) > 1e-6:
                            sheets[s_idx].dim_texts_mm.append(t_entry)
                        else:
                            sheets[s_idx].note_texts_mm.append(t_entry)
                    pos = sstart + slen * 2
                    continue
        pos += 1

    # Gắn từng Drawing View vào đúng Sheet và khớp với uiViewBucket_c theo vector pháp tuyến 3D
    used_buckets: set[int] = set()
    for vi, (v_off, r, (ox, oy, oz), sc, (cx, cy, cz)) in enumerate(raw_views):
        s_idx = _sheet_idx_for_offset(v_off)
        sheets[s_idx].n_views += 1
        # Pháp tuyến hướng nhìn trong ma trận R (cột thứ 3 của ma trận column-major: r[2], r[5], r[8])
        vz = (r[2], r[5], r[8])
        chosen_bi: int | None = None
        best_dot = 0.95
        for bi, b_norm in enumerate(bucket_normals):
            if b_norm is not None and bi not in used_buckets:
                dot = abs(vz[0] * b_norm[0] + vz[1] * b_norm[1] + vz[2] * b_norm[2])
                if dot > best_dot:
                    best_dot = dot
                    chosen_bi = bi
        if chosen_bi is None:
            chosen_bi = vi if vi < len(buckets) else (0 if buckets else None)
        if chosen_bi is not None and chosen_bi < len(buckets):
            used_buckets.add(chosen_bi)
            b_curves = buckets[chosen_bi]
        else:
            b_curves = []

        for coords_m in b_curves:
            pts_2d: list[tuple[float, float, float]] = []
            for x, y, z in coords_m:
                rx = r[0] * x + r[3] * y + r[6] * z
                ry = r[1] * x + r[4] * y + r[7] * z
                sx_mm = round((cx + ox + sc * rx) * 1000.0, 4)
                sy_mm = round((cy + oy + sc * ry) * 1000.0, 4)
                if not pts_2d or pts_2d[-1] != (sx_mm, sy_mm, 0.0):
                    pts_2d.append((sx_mm, sy_mm, 0.0))
            if len(pts_2d) >= 2:
                sheets[s_idx].view_polylines_2d_mm.append(pts_2d)

    # Tính khổ giấy từng Sheet, lọc chữ thừa ngoài mép giấy và dịch ngang (offset_x_mm) nếu có nhiều tờ
    cum_offset_x = 0.0
    for sh in sheets:
        all_lines = sh.border_lines_mm or sh.dim_lines_mm
        if all_lines:
            xs = [p[0] for a, b in all_lines for p in (a, b)]
            ys = [p[1] for a, b in all_lines for p in (a, b)]
            sx0, sx1, sy0, sy1 = min(xs) - 1.0, max(xs) + 1.0, min(ys) - 1.0, max(ys) + 1.0
            sh.width_mm = round(max(210.0, max(xs)), 2)
            sh.height_mm = round(max(148.0, max(ys)), 2)
            sh.note_texts_mm = [t for t in sh.note_texts_mm if sx0 <= t[0] <= sx1 and sy0 <= t[1] <= sy1]
            sh.dim_texts_mm = [t for t in sh.dim_texts_mm if sx0 <= t[0] <= sx1 and sy0 <= t[1] <= sy1]
        sh.offset_x_mm = cum_offset_x
        if cum_offset_x > 0.0:
            dx = cum_offset_x
            sh.border_lines_mm = [((a[0] + dx, a[1], a[2]), (b[0] + dx, b[1], b[2])) for a, b in sh.border_lines_mm]
            sh.border_circles_mm = [(xc + dx, yc, rad) for xc, yc, rad in sh.border_circles_mm]
            sh.border_arcs_mm = [[(p[0] + dx, p[1], p[2]) for p in arc] for arc in sh.border_arcs_mm]
            sh.view_polylines_2d_mm = [[(p[0] + dx, p[1], p[2]) for p in poly] for poly in sh.view_polylines_2d_mm]
            sh.dim_lines_mm = [((a[0] + dx, a[1], a[2]), (b[0] + dx, b[1], b[2])) for a, b in sh.dim_lines_mm]
            sh.dim_tris_mm = [[(p[0] + dx, p[1], p[2]) for p in tri] for tri in sh.dim_tris_mm]
            sh.dim_circles_mm = [(xc + dx, yc, rad) for xc, yc, rad in sh.dim_circles_mm]
            sh.dim_arcs_mm = [[(p[0] + dx, p[1], p[2]) for p in arc] for arc in sh.dim_arcs_mm]
            sh.dim_texts_mm = [(tx + dx, ty, th, v, s) for tx, ty, th, v, s in sh.dim_texts_mm]
            sh.note_texts_mm = [(tx + dx, ty, th, v, s) for tx, ty, th, v, s in sh.note_texts_mm]
        cum_offset_x += sh.width_mm + 50.0

    if sheet_filter is not None:
        filtered = [sh for sh in sheets if sh.index == sheet_filter]
        if not filtered:
            raise ValueError(f"Bản vẽ chỉ có {len(sheets)} tờ, không có tờ số {sheet_filter}")
        sheets = filtered

    # 4. Trích xuất các mặt 3D (uoTempFaceTessData_c) trong VBLists và gộp các tam giác đồng phẳng
    pat_face = b"\x04\x00\x00\x00\x08\x00\x00\x00\x02\x00\x00\x00"
    pos = 0
    model_faces_3d_mm: list[tuple[tuple[float, float, float], list[tuple[float, float, float]]]] = []
    n_3d_faces = 0

    def _pt_mm(verts_tuple: tuple, idx_v: int) -> tuple[float, float, float]:
        return (
            round(-verts_tuple[idx_v * 3] * 1000.0, 3),
            round(-verts_tuple[idx_v * 3 + 1] * 1000.0, 3),
            round(verts_tuple[idx_v * 3 + 2] * 1000.0, 3),
        )

    def _normal(p0, p1, p2):
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        if ln < 1e-6:
            return None
        return (nx / ln, ny / ln, nz / ln)

    while True:
        idx = vb.find(pat_face, pos)
        if idx == -1:
            break
        p = idx + 12
        if p + 4 > len(vb):
            break
        n_strips = struct.unpack_from("<I", vb, p)[0]
        p += 4
        if 1 <= n_strips <= 10000 and p + n_strips * 4 + 16 <= len(vb):
            strip_lens = struct.unpack_from(f"<{n_strips}I", vb, p)
            p += n_strips * 4
            stride, attr, dim, n_verts = struct.unpack_from("<IIII", vb, p)
            p += 16
            if stride == 12 and attr == 100 and n_verts == sum(strip_lens) and p + n_verts * 12 <= len(vb):
                n_3d_faces += 1
                verts = struct.unpack_from(f"<{n_verts * 3}f", vb, p)
                v_off = 0
                for slen in strip_lens:
                    k = 0
                    while k < slen - 2:
                        p0 = _pt_mm(verts, v_off + k)
                        p1 = _pt_mm(verts, v_off + k + 1)
                        p2 = _pt_mm(verts, v_off + k + 2)
                        if k % 2 == 1:
                            p1, p2 = p2, p1
                        n = _normal(p0, p1, p2)
                        if n is None:
                            k += 1
                            continue
                        if k + 3 < slen:
                            p3 = _pt_mm(verts, v_off + k + 3)
                            d_pl = abs(
                                (p3[0] - p0[0]) * n[0]
                                + (p3[1] - p0[1]) * n[1]
                                + (p3[2] - p0[2]) * n[2]
                            )
                            if d_pl < 0.01:
                                q = [p0, p1, p3, p2] if (k % 2 == 0) else [p0, p1, p2, p3]
                                clean_q = [q[m] for m in range(len(q)) if q[m] != q[m - 1]]
                                if len(clean_q) >= 3:
                                    model_faces_3d_mm.append((n, clean_q))
                                k += 2
                                continue
                        model_faces_3d_mm.append((n, [p0, p1, p2]))
                        k += 1
                    v_off += slen
                pos = p + n_verts * 12
                continue
        pos = idx + 12

    all_sheet_lines = [ln for sh in sheets for ln in (sh.border_lines_mm + sh.dim_lines_mm)]
    all_sheet_tris = [tr for sh in sheets for tr in sh.dim_tris_mm]
    all_sheet_circles = [c for sh in sheets for c in (sh.border_circles_mm + sh.dim_circles_mm)]
    all_texts = [t for sh in sheets for t in (sh.note_texts_mm + sh.dim_texts_mm)]
    all_view_polys = [vp for sh in sheets for vp in sh.view_polylines_2d_mm]

    return SldDrwData(
        sheets=sheets,
        sheet_lines_mm=all_sheet_lines,
        sheet_tris_mm=all_sheet_tris,
        sheet_circles_mm=all_sheet_circles,
        texts_mm=all_texts,
        view_polylines_2d_mm=all_view_polys,
        model_polylines_3d_mm=model_polylines_3d_mm,
        model_faces_3d_mm=model_faces_3d_mm,
        model_color_rgb=model_color_rgb,
        referenced_paths=referenced_paths,
        n_views=sum(sh.n_views for sh in sheets),
        n_3d_faces=n_3d_faces,
    )


def write_slddrw_step(data: SldDrwData, dst: Path, stem: str = "Drawing") -> None:
    """Xuất dữ liệu SldDrwData ra file STEP chuẩn ISO 10303-21 (AP214) chia sẵn Layer theo từng tờ
    và gắn màu sắc AP214 (STYLED_ITEM + COLOUR_RGB):
      - [SheetN_]01_Khung_Ban_Ve : Khung bản vẽ, khung tên, bảng biểu (Xám đậm)
      - [SheetN_]02_Hinh_Chieu   : Các hình chiếu 2D (Đen đậm)
      - [SheetN_]03_Kich_Thuoc   : Đường kích thước, đường gióng, mũi tên, số đo (Xanh dương kỹ thuật)
      - [SheetN_]04_Chu_Ghi_Chu  : Chữ khung tên & ghi chú kỹ thuật (Xanh lục đậm)
      - 05_Model_3D              : Mô hình 3D nhúng sẵn với màu vật liệu SolidWorks
    """
    lines: list[str] = []
    eid = 0

    def add(body: str) -> int:
        nonlocal eid
        eid += 1
        lines.append(f"#{eid} = {body};")
        return eid

    pt_cache: dict[tuple[float, float, float], int] = {}

    def get_pt(pt: tuple[float, float, float]) -> int:
        pid = pt_cache.get(pt)
        if pid is None:
            pid = add(f"CARTESIAN_POINT('',({pt[0]:.4f},{pt[1]:.4f},{pt[2]:.4f}))")
            pt_cache[pt] = pid
        return pid

    dir_cache: dict[tuple[float, float, float], int] = {}

    def get_dir(d: tuple[float, float, float]) -> int:
        dq = (round(d[0], 6), round(d[1], 6), round(d[2], 6))
        did = dir_cache.get(dq)
        if did is None:
            did = add(f"DIRECTION('',({dq[0]:.6f},{dq[1]:.6f},{dq[2]:.6f}))")
            dir_cache[dq] = did
        return did

    app_ctx = add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app_ctx})")
    u_len = add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    u_ang = add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    u_sol = add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = add(
        f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-03),#{u_len},"
        "'distance_accuracy_value','confusion accuracy')"
    )
    geom_ctx = add(
        f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc})) "
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{u_len},#{u_ang},#{u_sol})) "
        "REPRESENTATION_CONTEXT('Context3D','3D Context with UNIT and UNCERTAINTY') )"
    )
    prod_ctx = add(f"PRODUCT_CONTEXT('',#{app_ctx},'mechanical')")
    pdef_ctx = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app_ctx},'design')")

    p_orig = get_pt((0.0, 0.0, 0.0))
    d_z = get_dir((0.0, 0.0, 1.0))
    d_x = get_dir((1.0, 0.0, 0.0))
    ax_world = add(f"AXIS2_PLACEMENT_3D('',#{p_orig},#{d_z},#{d_x})")
    curve_font = add("DRAUGHTING_PRE_DEFINED_CURVE_FONT('continuous')")

    styled_items: list[int] = []

    def add_curve_product(prod_name: str, curve_ids: list[int],
                          rgb: tuple[float, float, float], width_mm: float = 0.25) -> None:
        if not curve_ids:
            return
        pr = add(f"PRODUCT('{prod_name}','{prod_name}','',(#{prod_ctx}))")
        pf = add(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#{pr},.NOT_KNOWN.)")
        pd = add(f"PRODUCT_DEFINITION('design','',#{pf},#{pdef_ctx})")
        ps = add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
        c_refs = ",".join(f"#{i}" for i in curve_ids)
        gcs = add(f"GEOMETRIC_CURVE_SET('',({c_refs}))")
        rep = add(
            f"GEOMETRICALLY_BOUNDED_WIREFRAME_SHAPE_REPRESENTATION('',(#{gcs},#{ax_world}),#{geom_ctx})"
        )
        add(f"SHAPE_DEFINITION_REPRESENTATION(#{ps},#{rep})")
        col = add(f"COLOUR_RGB('',{rgb[0]:.4f},{rgb[1]:.4f},{rgb[2]:.4f})")
        c_style = add(f"CURVE_STYLE('',#{curve_font},POSITIVE_LENGTH_MEASURE({width_mm:.2f}),#{col})")
        psa = add(f"PRESENTATION_STYLE_ASSIGNMENT((#{c_style}))")
        styled_items.append(add(f"STYLED_ITEM('',(#{psa}),#{gcs})"))

    def make_poly(pts: list[tuple[float, float, float]]) -> int | None:
        pids: list[int] = []
        for p in pts:
            pid = get_pt(p)
            if not pids or pids[-1] != pid:
                pids.append(pid)
        if len(pids) >= 2:
            refs = ",".join(f"#{i}" for i in pids)
            return add(f"POLYLINE('',({refs}))")
        return None

    multi_sheet = len(data.sheets) > 1
    for sh in data.sheets:
        prefix = f"{sh.name}_" if multi_sheet else ""

        # Layer 1: 01_Khung_Ban_Ve (BORDER)
        c_border: list[int] = []
        for p0, p1 in sh.border_lines_mm:
            cid = make_poly([p0, p1])
            if cid:
                c_border.append(cid)
        for xc, yc, rad in sh.border_circles_mm:
            pc = get_pt((xc, yc, 0.0))
            ax_c = add(f"AXIS2_PLACEMENT_3D('',#{pc},#{d_z},#{d_x})")
            c_border.append(add(f"CIRCLE('',#{ax_c},{rad:.4f})"))
        for arc_pts in sh.border_arcs_mm:
            cid = make_poly(arc_pts)
            if cid:
                c_border.append(cid)
        add_curve_product(f"{prefix}01_Khung_Ban_Ve", c_border, (0.25, 0.25, 0.25), 0.25)

        # Layer 2: 02_Hinh_Chieu (VIEWS)
        c_views: list[int] = []
        for poly in sh.view_polylines_2d_mm:
            cid = make_poly(poly)
            if cid:
                c_views.append(cid)
        add_curve_product(f"{prefix}02_Hinh_Chieu", c_views, (0.08, 0.08, 0.08), 0.35)

        # Layer 3: 03_Kich_Thuoc (DIMENSIONS)
        c_dims: list[int] = []
        for p0, p1 in sh.dim_lines_mm:
            cid = make_poly([p0, p1])
            if cid:
                c_dims.append(cid)
        for tri in sh.dim_tris_mm:
            cid = make_poly(tri + [tri[0]])
            if cid:
                c_dims.append(cid)
        for xc, yc, rad in sh.dim_circles_mm:
            pc = get_pt((xc, yc, 0.0))
            ax_c = add(f"AXIS2_PLACEMENT_3D('',#{pc},#{d_z},#{d_x})")
            c_dims.append(add(f"CIRCLE('',#{ax_c},{rad:.4f})"))
        for arc_pts in sh.dim_arcs_mm:
            cid = make_poly(arc_pts)
            if cid:
                c_dims.append(cid)
        for tx, ty, th, vert, txt in sh.dim_texts_mm:
            for st_pts in _text_to_polylines(txt, tx, ty, th, vertical=vert):
                cid = make_poly(st_pts)
                if cid:
                    c_dims.append(cid)
        add_curve_product(f"{prefix}03_Kich_Thuoc", c_dims, (0.00, 0.35, 0.80), 0.18)

        # Layer 4: 04_Chu_Ghi_Chu (TEXT_NOTES)
        c_notes: list[int] = []
        for tx, ty, th, vert, txt in sh.note_texts_mm:
            for st_pts in _text_to_polylines(txt, tx, ty, th, vertical=vert):
                cid = make_poly(st_pts)
                if cid:
                    c_notes.append(cid)
        add_curve_product(f"{prefix}04_Chu_Ghi_Chu", c_notes, (0.07, 0.38, 0.22), 0.20)

    # Layer 5: 05_Model_3D (Mô hình 3D kèm màu vật liệu SolidWorks)
    face_ids_3d: list[int] = []
    for n, poly_pts in data.model_faces_3d_mm:
        pids: list[int] = []
        for p in poly_pts:
            pid = get_pt(p)
            if not pids or pids[-1] != pid:
                pids.append(pid)
        if len(pids) >= 2 and pids[0] == pids[-1]:
            pids.pop()
        if len(pids) < 3 or len(set(pids)) < 3:
            continue
        p0, p1 = poly_pts[0], poly_pts[1]
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        lu = math.sqrt(ux * ux + uy * uy + uz * uz)
        if lu < 1e-6:
            continue
        ref_d = (ux / lu, uy / lu, uz / lu)
        dn = get_dir(n)
        dr = get_dir(ref_d)
        ax_f = add(f"AXIS2_PLACEMENT_3D('',#{pids[0]},#{dn},#{dr})")
        pl_f = add(f"PLANE('',#{ax_f})")
        p_refs = ",".join(f"#{i}" for i in pids)
        ploop = add(f"POLY_LOOP('',({p_refs}))")
        fbound = add(f"FACE_OUTER_BOUND('',#{ploop},.T.)")
        face_ids_3d.append(add(f"FACE_SURFACE('',(#{fbound}),#{pl_f},.T.)"))

    if face_ids_3d:
        m_name = "05_Model_3D"
        pr2 = add(f"PRODUCT('{m_name}','{m_name}','',(#{prod_ctx}))")
        pf2 = add(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#{pr2},.NOT_KNOWN.)")
        pd2 = add(f"PRODUCT_DEFINITION('design','',#{pf2},#{pdef_ctx})")
        ps2 = add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd2})")
        f_refs = ",".join(f"#{i}" for i in face_ids_3d)
        oshell = add(f"OPEN_SHELL('',({f_refs}))")
        sbsm = add(f"SHELL_BASED_SURFACE_MODEL('',(#{oshell}))")
        rep2 = add(f"MANIFOLD_SURFACE_SHAPE_REPRESENTATION('',(#{sbsm},#{ax_world}),#{geom_ctx})")
        add(f"SHAPE_DEFINITION_REPRESENTATION(#{ps2},#{rep2})")
        mr, mg, mb = data.model_color_rgb
        m_col = add(f"COLOUR_RGB('',{mr:.4f},{mg:.4f},{mb:.4f})")
        fas_col = add(f"FILL_AREA_STYLE_COLOUR('',#{m_col})")
        fas = add(f"FILL_AREA_STYLE('',(#{fas_col}))")
        ss_fill = add(f"SURFACE_STYLE_FILL_AREA(#{fas})")
        ss_side = add(f"SURFACE_SIDE_STYLE('',(#{ss_fill}))")
        ss_usage = add(f"SURFACE_STYLE_USAGE(.BOTH.,#{ss_side})")
        psa_m = add(f"PRESENTATION_STYLE_ASSIGNMENT((#{ss_usage}))")
        styled_items.append(add(f"STYLED_ITEM('',(#{psa_m}),#{sbsm})"))
    elif data.model_polylines_3d_mm:
        c_3d: list[int] = []
        for poly in data.model_polylines_3d_mm:
            cid = make_poly(poly)
            if cid:
                c_3d.append(cid)
        add_curve_product("05_Model_3D", c_3d, data.model_color_rgb, 0.35)

    if styled_items:
        st_refs = ",".join(f"#{i}" for i in styled_items)
        add(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({st_refs}),#{geom_ctx})")

    dst.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION(('SolidWorks Drawing .SLDDRW converted by sw2step.py'),'2;1');\n"
        f"FILE_NAME('{dst.name}','2026-10-22T00:00:00',('sw2step'),(''),'sw2step.py','sw2step.py','');\n"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )
    footer = "\nENDSEC;\nEND-ISO-10303-21;\n"
    dst.write_text(header + "\n".join(lines) + footer, encoding="utf-8")


def write_slddrw_dxf(data: SldDrwData, dst: Path) -> None:
    """Xuất bản vẽ 2D từ .SLDDRW ra định dạng AutoCAD DXF (AC1009/R12) chuẩn với bảng LAYER
    đặt tên rõ ràng theo loại (01_Khung_Ban_Ve, 02_Hinh_Chieu, 03_Kich_Thuoc, 04_Chu_Ghi_Chu)."""
    multi_sheet = len(data.sheets) > 1
    layer_defs: list[tuple[str, int]] = []
    for sh in data.sheets:
        pfx = f"{sh.name}_" if multi_sheet else ""
        layer_defs.extend([
            (f"{pfx}01_Khung_Ban_Ve", 7),   # Trắng/Đen
            (f"{pfx}02_Hinh_Chieu", 7),     # Trắng/Đen
            (f"{pfx}03_Kich_Thuoc", 5),     # Xanh dương (ACI 5)
            (f"{pfx}04_Chu_Ghi_Chu", 3),    # Xanh lá (ACI 3)
        ])

    out: list[str] = [
        "0", "SECTION", "2", "HEADER",
        "9", "$INSUNITS", "70", "4",
        "0", "ENDSEC",
        "0", "SECTION", "2", "TABLES",
        "0", "TABLE", "2", "LAYER", "70", str(len(layer_defs)),
    ]
    for lname, aci_color in layer_defs:
        out.extend([
            "0", "LAYER",
            "2", lname,
            "70", "0",
            "62", str(aci_color),
            "6", "CONTINUOUS",
        ])
    out.extend([
        "0", "ENDTAB",
        "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
    ])

    def add_line(x1: float, y1: float, x2: float, y2: float, layer: str) -> None:
        out.extend([
            "0", "LINE", "8", layer,
            "10", f"{x1:.4f}", "20", f"{y1:.4f}", "30", "0.0",
            "11", f"{x2:.4f}", "21", f"{y2:.4f}", "31", "0.0",
        ])

    def add_poly(pts: list[tuple[float, float, float]], layer: str) -> None:
        for k in range(len(pts) - 1):
            add_line(pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1], layer)

    for sh in data.sheets:
        pfx = f"{sh.name}_" if multi_sheet else ""
        l_border = f"{pfx}01_Khung_Ban_Ve"
        l_views = f"{pfx}02_Hinh_Chieu"
        l_dims = f"{pfx}03_Kich_Thuoc"
        l_notes = f"{pfx}04_Chu_Ghi_Chu"

        for p0, p1 in sh.border_lines_mm:
            add_line(p0[0], p0[1], p1[0], p1[1], l_border)
        for xc, yc, rad in sh.border_circles_mm:
            out.extend([
                "0", "CIRCLE", "8", l_border,
                "10", f"{xc:.4f}", "20", f"{yc:.4f}", "30", "0.0",
                "40", f"{rad:.4f}",
            ])
        for arc_pts in sh.border_arcs_mm:
            add_poly(arc_pts, l_border)

        for poly in sh.view_polylines_2d_mm:
            add_poly(poly, l_views)

        for p0, p1 in sh.dim_lines_mm:
            add_line(p0[0], p0[1], p1[0], p1[1], l_dims)
        for tri in sh.dim_tris_mm:
            add_poly(tri + [tri[0]], l_dims)
        for xc, yc, rad in sh.dim_circles_mm:
            out.extend([
                "0", "CIRCLE", "8", l_dims,
                "10", f"{xc:.4f}", "20", f"{yc:.4f}", "30", "0.0",
                "40", f"{rad:.4f}",
            ])
        for arc_pts in sh.dim_arcs_mm:
            add_poly(arc_pts, l_dims)
        for tx, ty, th, vert, txt in sh.dim_texts_mm:
            out.extend([
                "0", "TEXT", "8", l_dims,
                "10", f"{tx:.4f}", "20", f"{ty:.4f}", "30", "0.0",
                "40", f"{th:.4f}",
                "1", txt,
                "50", "90.0" if vert else "0.0",
            ])

        for tx, ty, th, vert, txt in sh.note_texts_mm:
            out.extend([
                "0", "TEXT", "8", l_notes,
                "10", f"{tx:.4f}", "20", f"{ty:.4f}", "30", "0.0",
                "40", f"{th:.4f}",
                "1", txt,
                "50", "90.0" if vert else "0.0",
            ])

    out.extend(["0", "ENDSEC", "0", "EOF", ""])
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(out), encoding="utf-8")


def render_slddrw_svg_string(data: SldDrwData, sheet_index: int | None = None) -> str:
    """Kết xuất bản vẽ 2D (hoặc 1 tờ cụ thể) ra chuỗi SVG chuẩn tỷ lệ 1:1 theo mm, chia sẵn <g id=...>."""
    target_sheets = [sh for sh in data.sheets if sheet_index is None or sh.index == sheet_index]
    if not target_sheets:
        target_sheets = data.sheets

    if len(target_sheets) == 1:
        sh0 = target_sheets[0]
        dx_shift = -sh0.offset_x_mm
        total_w = sh0.width_mm
        max_h = sh0.height_mm
    else:
        dx_shift = 0.0
        last_sh = target_sheets[-1]
        total_w = last_sh.offset_x_mm + last_sh.width_mm
        max_h = max(s.height_mm for s in target_sheets)

    els: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.2f}mm" height="{max_h:.2f}mm" '
        f'viewBox="0 0 {total_w:.2f} {max_h:.2f}">',
        f'<rect width="{total_w:.2f}" height="{max_h:.2f}" fill="#ffffff"/>',
    ]

    multi = len(target_sheets) > 1
    for sh in target_sheets:
        H = max_h
        pfx = f"{sh.name}_" if multi else ""
        # Layer 1: Khung bản vẽ
        els.append(
            f'<g id="{pfx}01_Khung_Ban_Ve" stroke="#333333" fill="none" '
            'stroke-width="0.22" stroke-linecap="round" stroke-linejoin="round">'
        )
        for p0, p1 in sh.border_lines_mm:
            els.append(
                f'<line x1="{p0[0] + dx_shift:.3f}" y1="{H - p0[1]:.3f}" '
                f'x2="{p1[0] + dx_shift:.3f}" y2="{H - p1[1]:.3f}"/>'
            )
        for xc, yc, rad in sh.border_circles_mm:
            els.append(f'<circle cx="{xc + dx_shift:.3f}" cy="{H - yc:.3f}" r="{rad:.3f}"/>')
        for arc_pts in sh.border_arcs_mm:
            pts_s = " ".join(f"{p[0] + dx_shift:.3f},{H - p[1]:.3f}" for p in arc_pts)
            els.append(f'<polyline points="{pts_s}"/>')
        els.append("</g>")

        # Layer 2: Hình chiếu 2D
        els.append(
            f'<g id="{pfx}02_Hinh_Chieu" stroke="#000000" fill="none" '
            'stroke-width="0.38" stroke-linecap="round" stroke-linejoin="round">'
        )
        for poly in sh.view_polylines_2d_mm:
            pts_s = " ".join(f"{p[0] + dx_shift:.3f},{H - p[1]:.3f}" for p in poly)
            els.append(f'<polyline points="{pts_s}"/>')
        els.append("</g>")

        # Layer 3: Kích thước
        els.append(
            f'<g id="{pfx}03_Kich_Thuoc" stroke="#0055cc" fill="none" '
            'stroke-width="0.18" stroke-linecap="round" stroke-linejoin="round">'
        )
        for p0, p1 in sh.dim_lines_mm:
            els.append(
                f'<line x1="{p0[0] + dx_shift:.3f}" y1="{H - p0[1]:.3f}" '
                f'x2="{p1[0] + dx_shift:.3f}" y2="{H - p1[1]:.3f}"/>'
            )
        for tri in sh.dim_tris_mm:
            pts_s = " ".join(f"{p[0] + dx_shift:.3f},{H - p[1]:.3f}" for p in tri)
            els.append(f'<polygon points="{pts_s}" fill="#0055cc" stroke="#0055cc" stroke-width="0.12"/>')
        for xc, yc, rad in sh.dim_circles_mm:
            els.append(f'<circle cx="{xc + dx_shift:.3f}" cy="{H - yc:.3f}" r="{rad:.3f}"/>')
        for arc_pts in sh.dim_arcs_mm:
            pts_s = " ".join(f"{p[0] + dx_shift:.3f},{H - p[1]:.3f}" for p in arc_pts)
            els.append(f'<polyline points="{pts_s}"/>')
        for tx, ty, th, vert, txt in sh.dim_texts_mm:
            sx, sy = tx + dx_shift, H - ty
            esc = html.escape(txt)
            if vert:
                els.append(
                    f'<text x="{sx:.3f}" y="{sy:.3f}" font-family="osifont, Arial, sans-serif" '
                    f'font-size="{th:.2f}" fill="#0055cc" stroke="none" '
                    f'transform="rotate(-90 {sx:.3f} {sy:.3f})">{esc}</text>'
                )
            else:
                els.append(
                    f'<text x="{sx:.3f}" y="{sy:.3f}" font-family="osifont, Arial, sans-serif" '
                    f'font-size="{th:.2f}" fill="#0055cc" stroke="none">{esc}</text>'
                )
        els.append("</g>")

        # Layer 4: Chữ & Ghi chú khung tên
        els.append(f'<g id="{pfx}04_Chu_Ghi_Chu" font-family="osifont, Arial, sans-serif" fill="#111111">')
        for tx, ty, th, vert, txt in sh.note_texts_mm:
            sx, sy = tx + dx_shift, H - ty
            esc = html.escape(txt)
            if vert:
                els.append(
                    f'<text x="{sx:.3f}" y="{sy:.3f}" font-size="{th:.2f}" '
                    f'transform="rotate(-90 {sx:.3f} {sy:.3f})">{esc}</text>'
                )
            else:
                els.append(f'<text x="{sx:.3f}" y="{sy:.3f}" font-size="{th:.2f}">{esc}</text>')
        els.append("</g>")

    els.append("</svg>\n")
    return "\n".join(els)


def write_slddrw_svg(data: SldDrwData, dst: Path) -> None:
    """Xuất bản vẽ 2D từ .SLDDRW ra file SVG chuẩn (tỷ lệ 1:1 theo mm, chia nhóm <g> theo Layer)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(render_slddrw_svg_string(data), encoding="utf-8")


def inspect_slddrw(src: Path) -> None:
    """In cấu trúc bên trong file .SLDDRW, danh sách các Sheet, bảng màu và số đối tượng mỗi Layer."""
    with src.open("rb") as fh:
        head = fh.read(4).hex()
    print(f"== {src.name}  ({src.stat().st_size:,} byte; 4 byte đầu: {head})")
    try:
        streams = unpack_sld_gcontainer(src)
    except ValueError as ex:
        print(f"   Container: {ex}")
        return
    print(f"   {len(streams)} luồng dữ liệu (lớn nhất trước):")
    for name, d in sorted(streams.items(), key=lambda kv: -len(kv[1]))[:25]:
        print(f"   {len(d):>12,}  {name}")
    for need in ("Contents/DisplayLists", "Contents/VBLists", "swXmlContents/xmlstream-2"):
        if need not in streams:
            print(f"   ! thiếu luồng mà bộ giải mã cần: {need}")
    d = parse_slddrw_geometry(src)
    r, g, b = (int(round(c * 255)) for c in d.model_color_rgb)
    print(
        f"   Tổng quan: {len(d.sheets)} tờ (sheet) | {d.n_views} hình chiếu | "
        f"Mô hình 3D: {d.n_3d_faces} mặt CAD ({len(d.model_faces_3d_mm)} đa giác), màu RGB=({r},{g},{b})"
    )
    for sh in d.sheets:
        print(
            f"   - Tờ {sh.index} [{sh.name}] ({sh.width_mm:.0f}x{sh.height_mm:.0f}mm, offset_x={sh.offset_x_mm:.0f}mm): "
            f"Khung={len(sh.border_lines_mm)} đoạn + {len(sh.border_circles_mm)} tròn | "
            f"Hình chiếu={sh.n_views} view ({len(sh.view_polylines_2d_mm)} nét) | "
            f"Kích thước={len(sh.dim_lines_mm)} đoạn + {len(sh.dim_tris_mm)} mũi tên + {len(sh.dim_texts_mm)} số đo | "
            f"Chữ khung tên={len(sh.note_texts_mm)} dòng"
        )
    for p in d.referenced_paths[:10]:
        print(f"   tham chiếu: {p}")


def convert_slddrw_builtin(src: Path, dst: Path, sheet_filter: int | None = None) -> tuple[str, str]:
    """Chuyển đổi trực tiếp file .SLDDRW sang .step / .dxf / .svg bằng bộ giải mã tích hợp."""
    data = parse_slddrw_geometry(src, sheet_filter=sheet_filter)
    if not (data.view_polylines_2d_mm or data.sheet_lines_mm or data.model_faces_3d_mm):
        return "FAIL", "Không tìm thấy dữ liệu hình học trong file .SLDDRW"
    ext = dst.suffix.lower()
    if ext == ".dxf":
        write_slddrw_dxf(data, dst)
    elif ext == ".svg":
        write_slddrw_svg(data, dst)
    else:
        write_slddrw_step(data, dst, stem=src.stem)
    n_sh = len(data.sheets)
    sh_names = ", ".join(sh.name for sh in data.sheets)
    note = (
        f"{n_sh} tờ ({sh_names}): 4 layer 2D ({len(data.sheet_lines_mm)} nét khung/kích thước, "
        f"{data.n_views} hình chiếu, {len(data.view_polylines_2d_mm)} nét chiếu, "
        f"{len(data.texts_mm)} chữ CAD) + 05_Model_3D ({data.n_3d_faces} mặt CAD có màu)"
    )
    return "OK", note


# --------------------------------------------------------------------------- #
# Backend 1: SolidWorks COM
# --------------------------------------------------------------------------- #
class SolidWorksBackend:
    name = "solidworks"
    DOC_TYPE = {EXT_PART: 1, EXT_ASM: 2, EXT_DRW: 3}    # swDocPART / swDocASSEMBLY / swDocDRAWING
    OPEN_OPTS = 1 | 2                                   # Silent | ReadOnly
    SAVE_OPTS = 1 | 2                                   # Silent | Copy

    @staticmethod
    def available() -> bool:
        if os.name != "nt":
            return False
        try:
            import pythoncom
            pythoncom.CLSIDFromProgID("SldWorks.Application")
            return True
        except Exception:
            return False

    def __init__(self) -> None:
        import pythoncom
        import win32com.client
        self.pythoncom = pythoncom
        self.win32 = win32com.client
        pythoncom.CoInitialize()
        self.started_by_us = False
        try:
            self.sw = self.win32.GetActiveObject("SldWorks.Application")
        except pythoncom.com_error:
            self.sw = self.win32.Dispatch("SldWorks.Application")
            self.started_by_us = True
            self.sw.Visible = False
            try:
                self.sw.UserControl = False
            except Exception:
                pass

    def _byref(self):
        return self.win32.VARIANT(self.pythoncom.VT_BYREF | self.pythoncom.VT_I4, 0)

    def convert(self, src: Path, dst: Path, sheet_filter: int | None = None, **_) -> tuple[str, str]:
        if src.suffix.lower() == EXT_DRW and dst.suffix.lower() in (".step", ".stp"):
            return convert_slddrw_builtin(src, dst, sheet_filter=sheet_filter)
        doc_type = self.DOC_TYPE[src.suffix.lower()]
        try:
            was_open = self.sw.GetOpenDocumentByName(str(src)) is not None
        except Exception:
            was_open = True
        err, warn = self._byref(), self._byref()
        model = self.sw.OpenDoc6(str(src), doc_type, self.OPEN_OPTS, "", err, warn)
        if model is None:
            return "FAIL", f"OpenDoc6 lỗi (code={err.value})"
        path = model.GetPathName
        path = path if isinstance(path, str) else str(src)
        try:
            if doc_type == 2:
                try:
                    model.ResolveAllLightWeightComponents(False)
                except Exception:
                    pass
            if dst.exists():
                dst.unlink()
            dst.parent.mkdir(parents=True, exist_ok=True)
            ret = model.SaveAs3(str(dst), 0, self.SAVE_OPTS)
            if not (dst.exists() and dst.stat().st_size > 0):
                return "FAIL", f"SaveAs3 lỗi (return={ret})"
            return ("WARN", f"open warning={warn.value}") if warn.value else ("OK", "")
        finally:
            if not was_open:
                try:
                    self.sw.CloseDoc(path)
                except Exception:
                    pass

    def close(self, quit_app: bool) -> None:
        if quit_app and self.started_by_us:
            try:
                self.sw.ExitApp()
            except Exception:
                pass
        self.pythoncom.CoUninitialize()


# --------------------------------------------------------------------------- #
# Backend 2: opensource (sld2step + sldprt2step + builtin .slddrw)
# --------------------------------------------------------------------------- #
def opensource_ready() -> bool:
    return all(p.exists() for p in (VENV_PY, SLD2STEP, SLDASM2STEP, SLDPRT2STEP))


_PATCH_FUNC = '''def _fit_legal_owners(template, owners) -> list:
    """Size a legal_owners flag list to the template's own element count."""
    have = template.values.get("legal_owners")
    n = len(have) if isinstance(have, list) else len(owners)
    out = list(owners)[:n]
    return out + [0] * (n - len(out))


'''


def _patch_sldprt2xt() -> None:
    """Áp bản vá của sld2step lên sldprt2xt==1.2.0 (tương đương patches/*.patch)."""
    out = subprocess.run(
        [str(VENV_PY), "-c", "import sldprt2xt, os; print(os.path.dirname(sldprt2xt.__file__))"],
        capture_output=True, text=True, check=True).stdout.strip()
    f = Path(out) / "xt" / "edit.py"
    text = f.read_text(encoding="utf-8")
    if "_fit_legal_owners" in text:
        return
    for old, new in (
        ("def mark_as_multi_body(", _PATCH_FUNC + "def mark_as_multi_body("),
        ("legal_owners=list(MULTI_BODY_LEGAL_OWNERS),",
         "legal_owners=_fit_legal_owners(template, MULTI_BODY_LEGAL_OWNERS),"),
        ("legal_owners=list(COLOUR_LEGAL_OWNERS),",
         "legal_owners=_fit_legal_owners(template, COLOUR_LEGAL_OWNERS),"),
    ):
        if old not in text:
            raise RuntimeError(f"Không áp được bản vá sldprt2xt (thiếu: {old!r}); "
                               "phiên bản sldprt2xt không khớp 1.2.0?")
        text = text.replace(old, new, 1)
    f.write_text(text, encoding="utf-8")


def _find_compatible_python() -> str | None:
    """Tìm Python 64-bit nằm trong khoảng PY_MIN..PY_MAX (hỗ trợ cả khi chạy bên trong FreeCAD)."""
    candidates = [sys.executable]
    if os.name == "nt":
        for ver in ("3.13", "3.12", "3.11", "3.10"):
            candidates.append(f"py -{ver}")
    for name in ("python3", "python3.13", "python3.12", "python3.11", "python3.10", "python"):
        w = shutil.which(name)
        if w and w not in candidates:
            candidates.append(w)
    for cand in candidates:
        cmd = cand.split() + [
            "-c",
            "import sys, struct; "
            "v = sys.version_info[:2]; "
            f"ok = ({PY_MIN} <= v <= {PY_MAX}) and (struct.calcsize('P')*8 == 64); "
            "print(sys.executable if ok else '')"
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            exe = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
            if r.returncode == 0 and exe and Path(exe).exists():
                return exe
        except Exception:
            continue
    return None


def setup_opensource() -> int:
    py_exe = _find_compatible_python()
    if not py_exe:
        v = sys.version_info[:2]
        log.error(
            "Không tìm thấy Python 64-bit bản %d.%d-%d.%d (hiện tại: %d.%d). "
            "Hãy cài Python 3.11 hoặc 3.12 64-bit từ https://python.org rồi chạy lại --setup.",
            PY_MIN[0], PY_MIN[1], PY_MAX[0], PY_MAX[1], v[0], v[1]
        )
        return 1
    if not shutil.which("git"):
        log.error("Cần cài git (https://git-scm.com) rồi chạy lại --setup")
        return 1
    TOOLS_HOME.mkdir(parents=True, exist_ok=True)
    for name, (url, ref) in REPOS.items():
        d = TOOLS_HOME / name
        if not d.exists():
            log.info("Clone %s", url)
            subprocess.run(["git", "clone", "-q", url, str(d)], check=True)
        if subprocess.run(["git", "-C", str(d), "checkout", "-q", ref],
                          capture_output=True).returncode != 0:
            subprocess.run(["git", "-C", str(d), "fetch", "-q", "origin"], check=True)
            subprocess.run(["git", "-C", str(d), "checkout", "-q", ref], check=True)
        log.info("%s @ %s", name, ref[:8])
    if not VENV_PY.exists():
        log.info("Tạo venv (%s): %s", py_exe, VENV_DIR)
        subprocess.run([py_exe, "-m", "venv", str(VENV_DIR)], check=True)
    log.info("Cài phụ thuộc (sldprt2xt, cadquery-ocp-novtk) ...")
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "-r",
                    str(TOOLS_HOME / "sld2step" / "requirements.txt")], check=True)
    _patch_sldprt2xt()
    rc, out = run([VENV_PY, "-c", "import OCP, sldprt2xt; print('ok')"], 120)
    if rc != 0 or "ok" not in out:
        log.error("Kiểm tra import thất bại:\n%s", out)
        return 1
    log.info("Sẵn sàng: %s", TOOLS_HOME)
    return 0


class OpenSourceBackend:
    name = "opensource"
    _STAT = re.compile(r"^(OK|WARN)\s+\S.*?:\s*(\d+) bodies \((\d+) valid\)", re.M)
    _ASM = re.compile(r"^(OK|FAIL)\s+.*?:\s*(\d+) instances, (\d+) parts converted, "
                      r"(\d+) failed, (\d+) unresolved", re.M)

    def __init__(self, timeout: int, fallback: bool, fast: bool = False) -> None:
        self.timeout = timeout
        self.fallback = fallback
        self.fast = fast

    @staticmethod
    def _validate(step: Path) -> bool:
        _, out = run([VENV_PY, "-c", _VALIDATE_SRC, step], 600)
        for line in reversed(out.splitlines()):
            if line.startswith("{"):
                try:
                    return bool(json.loads(line)["valid"])
                except (ValueError, KeyError):
                    break
        return False

    def convert(self, src: Path, dst: Path, fasteners: bool = False,
                asm_roots: list[Path] | None = None,
                sheet_filter: int | None = None) -> tuple[str, str]:
        ext_in = src.suffix.lower()
        if ext_in == EXT_DRW:
            return convert_slddrw_builtin(src, dst, sheet_filter=sheet_filter)
        with tempfile.TemporaryDirectory(prefix="sw2step_") as td:
            tmp = Path(td)
            if ext_in == EXT_ASM:
                status, note = self._assembly(src, dst, tmp, fasteners, asm_roots or [])
            else:
                status, note = self._part(src, dst, tmp)
            if status != "FAIL" and dst.exists():
                if inject_step_ap214_colors(dst, src):
                    note += " + gắn màu AP214"
            return status, note

    def _part(self, src: Path, dst: Path, tmp: Path) -> tuple[str, str]:
        a = tmp / "a"
        a.mkdir()
        rc, text = run([VENV_PY, SLD2STEP, src, "-o", a], self.timeout)
        step_a = a / (src.stem + ".step")
        m = self._STAT.search(text)
        n_bodies = int(m.group(2)) if m else 0
        ok_a = step_a.exists() and step_a.stat().st_size > 0 and bool(m) and n_bodies > 0
        clean = ok_a and m.group(1) == "OK" and m.group(2) == m.group(3)
        if m:
            w = re.search(r"warnings=\[(.*?)\]", text)
            note_a = f"sld2step: {m.group(2)} body, {m.group(3)} hợp lệ" + (
                f"; xấp xỉ: {w.group(1)}" if w and w.group(1) else "")
        else:
            fail = re.search(r"^FAIL.*$", text, re.M)
            note_a = "sld2step: " + (fail.group(0)[:200] if fail else last_line(text) or f"exit {rc}")

        if ok_a and (clean or self.fast or not self.fallback):
            place(step_a, dst)
            return ("OK" if clean else "WARN"), note_a
        if not self.fallback:
            return "FAIL", note_a

        b = tmp / "b.step"
        rc_b, text_b = run([VENV_PY, SLDPRT2STEP, src, "-o", b], self.timeout)
        ok_b = rc_b in (0, 2) and b.exists() and b.stat().st_size > 0
        note_b = "sldprt2step: " + (last_line(text_b, 160) or ("ok" if ok_b else f"exit {rc_b}"))

        if ok_a and ok_b:
            va, vb = self._validate(step_a), self._validate(b)
            if va or not vb:
                place(step_a, dst)
                tail = "" if va else " (cả hai không hợp lệ - hãy kiểm tra trong FreeCAD)"
                return ("OK" if va else "WARN"), f"{note_a} | {note_b} | chọn sld2step{tail}"
            place(b, dst)
            return "WARN", f"{note_a} | {note_b} | chọn sldprt2step (hợp lệ hơn)"
        if ok_a:
            place(step_a, dst)
            return "WARN", f"{note_a} | {note_b}"
        if ok_b:
            place(b, dst)
            return "WARN", f"{note_a} | {note_b} | dùng sldprt2step"
        return "FAIL", f"{note_a} | {note_b}"

    def _assembly(self, src: Path, dst: Path, tmp: Path, fasteners: bool,
                  roots: list[Path]) -> tuple[str, str]:
        emb = tmp / "embedded"
        cmd = [VENV_PY, "-c", _ASM_RUNNER_SRC, SLD2STEP.parent, src, emb, "-o", tmp]
        for r in [src.parent, *roots]:
            cmd += ["--root", r]
        if fasteners:
            cmd.append("--fasteners")
        rc, text = run(cmd, self.timeout)
        m_emb = re.search(r"EMBEDDED (\d+)", text)
        n_emb = int(m_emb.group(1)) if m_emb else 0
        step = tmp / (src.stem + ".step")
        m = self._ASM.search(text)
        if not (step.exists() and m and m.group(1) == "OK"):
            fail = re.search(r"^FAIL.*$", text, re.M)
            return "FAIL", fail.group(0)[:200] if fail else (last_line(text) or f"exit {rc}")
        inst, parts, failed, unresolved = (int(m.group(i)) for i in range(2, 6))
        mism = len(re.findall(r"^\s+config-mismatch:", text, re.M))
        place(step, dst)
        note = f"{inst} instance, {parts} part" + (f", {n_emb} part nhúng sẵn trong file" if n_emb else "")
        issues = []
        if failed:
            issues.append(f"{failed} part lỗi")
        if unresolved:
            issues.append(f"{unresolved} tham chiếu không tìm thấy")
        if mism:
            issues.append(f"{mism} cấu hình không khớp (dùng cấu hình đã lưu)")
        return ("WARN", note + "; " + ", ".join(issues)) if issues else ("OK", note)


class BuiltinDrwBackend:
    """Backend thuần Python xử lý riêng .SLDDRW ngay cả khi chưa cài SolidWorks hay --setup."""
    name = "builtin-drw"

    @staticmethod
    def convert(src: Path, dst: Path, sheet_filter: int | None = None, **_) -> tuple[str, str]:
        if src.suffix.lower() != EXT_DRW:
            return "FAIL", "Chỉ hỗ trợ .slddrw"
        return convert_slddrw_builtin(src, dst, sheet_filter=sheet_filter)


# --------------------------------------------------------------------------- #
# Tích hợp FreeCAD: chuyển đổi nhanh 1 file + Plugin Importer tự động
# --------------------------------------------------------------------------- #
def convert_single_for_freecad(
    src: Path,
    backend_pref: str = "auto",
    use_cache: bool = True,
    save_alongside: bool = False,
    fast: bool = True,
    fasteners: bool = False,
    timeout: int = 1800,
) -> tuple[Path, str, str]:
    """Chuyển đổi 1 file .sldprt/.sldasm/.slddrw sang .step nhanh nhất có thể để mở trong FreeCAD.
    Trả về (step_path, status, note)."""
    src = src.resolve()
    if not src.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {src}")

    dst = src.with_suffix(".step") if save_alongside else cache_path_for(src, fasteners=fasteners)
    if use_cache and dst.exists() and dst.stat().st_size > 0:
        if not save_alongside or dst.stat().st_mtime >= src.stat().st_mtime:
            return dst, "CACHE", f"Dùng lại bản STEP đã lưu ({dst.name})"

    if src.suffix.lower() == EXT_DRW:
        try:
            status, note = convert_slddrw_builtin(src, dst)
        except Exception as ex:
            raise RuntimeError(f"Không giải mã được bản vẽ .SLDDRW ({type(ex).__name__}): {ex}") from ex
        if status != "FAIL" and dst.exists() and dst.stat().st_size > 0:
            return dst, status, f"[builtin-drw] {note}"
        raise RuntimeError(f"Chuyển đổi .SLDDRW thất bại: {note}")

    chain: list = []
    sw_backend = None
    if backend_pref in ("auto", "solidworks") and SolidWorksBackend.available():
        try:
            sw_backend = SolidWorksBackend()
            chain.append(sw_backend)
        except Exception as ex:
            log.warning("Không khởi động được SolidWorks: %s", ex)
    if backend_pref in ("auto", "opensource"):
        if not opensource_ready():
            log.info("Backend opensource chưa có, đang tự động chạy --setup ...")
            if setup_opensource() != 0:
                raise RuntimeError(
                    "Backend opensource chưa được cài đặt. "
                    f"Hãy chạy: python \"{Path(__file__).resolve()}\" --setup"
                )
        chain.append(OpenSourceBackend(timeout=timeout, fallback=True, fast=fast))

    if not chain:
        raise RuntimeError("Không có backend khả dụng (cần SolidWorks hoặc chạy --setup).")

    try:
        last_note = ""
        for b in chain:
            status, note = b.convert(src, dst, fasteners=fasteners)
            last_note = note
            if status != "FAIL" and dst.exists() and dst.stat().st_size > 0:
                return dst, status, f"[{b.name}] {note}"
        raise RuntimeError(f"Chuyển đổi thất bại: {last_note}")
    finally:
        if sw_backend:
            sw_backend.close(quit_app=False)


_FREECAD_INIT_PY = '''# Auto-generated by sw2step.py --install-freecad
import FreeCAD
FreeCAD.addImportType("SolidWorks (*.sldprt *.sldasm *.slddrw *.SLDPRT *.SLDASM *.SLDDRW)", "importSLD")
'''

_FREECAD_IMPORT_SLD_PY = '''# Auto-generated by sw2step.py --install-freecad
"""FreeCAD Importer cho phép mở/kéo-thả trực tiếp file .SLDPRT, .SLDASM và .SLDDRW."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import FreeCAD

_MOD_DIR = Path(__file__).resolve().parent
if str(_MOD_DIR) not in sys.path:
    sys.path.insert(0, str(_MOD_DIR))

import importlib  # noqa: E402
import sw2step  # noqa: E402

_LOADED_MTIME = Path(sw2step.__file__).stat().st_mtime


def _refresh_core():
    """Nạp lại sw2step nếu file trên đĩa đã đổi (tránh chạy bản cũ còn nằm trong bộ nhớ FreeCAD)."""
    global sw2step, _LOADED_MTIME
    try:
        mt = Path(sw2step.__file__).stat().st_mtime
        if mt != _LOADED_MTIME:
            sw2step = importlib.reload(sw2step)
            _LOADED_MTIME = mt
    except Exception as ex:
        FreeCAD.Console.PrintWarning(f"[sw2step] Không nạp lại được sw2step: {ex}\\n")


def _get_qt_app_and_cursor():
    """Lấy (QApplication, WaitCursor) tương thích mọi bản FreeCAD (PySide / PySide2 / PySide6)."""
    for mod_name in ("PySide", "PySide6", "PySide2"):
        try:
            mod = __import__(mod_name)
            QtCore = getattr(mod, "QtCore", None)
            QtWidgets = getattr(mod, "QtWidgets", None) or getattr(mod, "QtGui", None)
            if QtCore and QtWidgets and hasattr(QtWidgets, "QApplication"):
                return QtWidgets.QApplication.instance(), QtCore.Qt.WaitCursor
        except Exception:
            continue
    return None, None


def _organize_drawing_in_freecad(doc, src_path: Path, existing_names: set[str]) -> None:
    """Tổ chức lại cây thư mục cho bản vẽ .SLDDRW trong FreeCAD:
      1) Gom các Layer 2D (01_Khung_Ban_Ve, 02_Hinh_Chieu, 03_Kich_Thuoc, 04_Chu_Ghi_Chu) vào Group
         và gán màu nét rõ ràng để người dùng bấm phím Space bật/tắt từng lớp.
      2) Tự động ẩn đối tượng 05_Model_3D để màn hình hiển thị thẳng bản vẽ 2D phẳng (vẫn có thể
         bật lại 05_Model_3D bằng phím Space khi muốn xem 3D).
      3) Tự động tạo trang bản vẽ 2D gốc (TechDraw::DrawPage) cho từng Sheet."""
    new_objs = [o for o in doc.Objects if o.Name not in existing_names]
    layer_colors = {
        "01_Khung_Ban_Ve": (0.25, 0.25, 0.25),
        "02_Hinh_Chieu": (0.05, 0.05, 0.05),
        "03_Kich_Thuoc": (0.00, 0.35, 0.80),
        "04_Chu_Ghi_Chu": (0.07, 0.38, 0.22),
    }
    grp_2d = doc.addObject("App::DocumentObjectGroup", "Ban_Ve_2D_Layers")
    grp_2d.Label = f"{src_path.stem}_2D_Layers"

    for obj in new_objs:
        lbl = getattr(obj, "Label", "") or ""
        vobj = getattr(obj, "ViewObject", None)
        if "05_Model_3D" in lbl:
            if vobj is not None:
                try:
                    vobj.Visibility = False
                    vobj.ShapeColor = (0.76, 0.78, 0.80)
                except Exception:
                    pass
        else:
            for k, col in layer_colors.items():
                if k in lbl:
                    try:
                        grp_2d.addObject(obj)
                    except Exception:
                        pass
                    if vobj is not None:
                        try:
                            vobj.LineColor = col
                            vobj.LineWidth = 2.0 if k == "02_Hinh_Chieu" else 1.2
                        except Exception:
                            pass
                    break

    # Tạo thêm trang bản vẽ 2D thực thụ bằng TechDraw (mỗi Sheet 1 trang)
    try:
        drw_data = sw2step.parse_slddrw_geometry(src_path)
        for sh in drw_data.sheets:
            svg_str = sw2step.render_slddrw_svg_string(drw_data, sheet_index=sh.index)
            page = doc.addObject("TechDraw::DrawPage", f"Page_{sh.name}")
            page.Label = f"Ban_Ve_2D_{sh.name}"
            tpl = doc.addObject("TechDraw::DrawSVGTemplate", f"Template_{sh.name}")
            blank_tpl = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{sh.width_mm:.2f}mm" '
                f'height="{sh.height_mm:.2f}mm" viewBox="0 0 {sh.width_mm:.2f} {sh.height_mm:.2f}"/>'
            )
            tpl_file = sw2step.CACHE_DIR / f"_tpl_{int(sh.width_mm)}x{int(sh.height_mm)}.svg"
            tpl_file.parent.mkdir(parents=True, exist_ok=True)
            if not tpl_file.exists():
                tpl_file.write_text(blank_tpl, encoding="utf-8")
            tpl.Template = str(tpl_file)
            page.Template = tpl
            sym = doc.addObject("TechDraw::DrawViewSymbol", f"SheetView_{sh.name}")
            sym.Label = f"{sh.name}_2D"
            sym.Symbol = svg_str
            sym.X = sh.width_mm / 2.0
            sym.Y = sh.height_mm / 2.0
            page.addView(sym)
    except Exception as ex:
        FreeCAD.Console.PrintWarning(f"[sw2step] Bỏ qua tạo trang TechDraw phụ ({ex})\\n")


def _load_step_into_doc(step_path: Path, doc_name: str | None, label: str,
                        src_path: Path | None = None, is_drawing: bool = False):
    """Nạp file STEP vào tài liệu FreeCAD, ưu tiên ImportGui để giữ nguyên màu sắc & cây lắp ghép."""
    if doc_name:
        try:
            doc = FreeCAD.getDocument(doc_name)
        except Exception:
            doc = FreeCAD.newDocument(doc_name)
    else:
        doc = FreeCAD.newDocument(label)

    existing_names = {o.Name for o in doc.Objects}

    if getattr(FreeCAD, "GuiUp", False):
        try:
            import ImportGui
            ImportGui.insert(str(step_path), doc.Name)
            if is_drawing and src_path is not None:
                _organize_drawing_in_freecad(doc, src_path, existing_names)
            doc.recompute()
            try:
                import FreeCADGui
                gui_doc = FreeCADGui.getDocument(doc.Name)
                if gui_doc and gui_doc.activeView():
                    if is_drawing:
                        gui_doc.activeView().viewTop()
                    else:
                        gui_doc.activeView().viewAxometric()
                    gui_doc.activeView().fitAll()
            except Exception:
                pass
            return doc
        except Exception as ex:
            FreeCAD.Console.PrintWarning(f"[sw2step] ImportGui lỗi ({ex}), chuyển sang Import.insert\\n")

    try:
        import Import
        Import.insert(str(step_path), doc.Name)
    except Exception:
        import Part
        shape = Part.Shape()
        shape.read(str(step_path))
        obj = doc.addObject("Part::Feature", label)
        obj.Label = label
        obj.Shape = shape

    if is_drawing and src_path is not None:
        _organize_drawing_in_freecad(doc, src_path, existing_names)
    doc.recompute()
    return doc


def _convert_with_feedback(filename: str) -> Path:
    _refresh_core()
    src = Path(filename).resolve()
    t0 = time.time()
    ver = getattr(sw2step, "SW2STEP_VERSION", "cu-khong-co-so-phien-ban")
    FreeCAD.Console.PrintMessage(f"[sw2step] v{ver} - Đang đọc {src.name} ...\\n")
    qt_app, wait_cursor = (None, None)
    if getattr(FreeCAD, "GuiUp", False):
        qt_app, wait_cursor = _get_qt_app_and_cursor()
        if qt_app and wait_cursor is not None:
            try:
                qt_app.setOverrideCursor(wait_cursor)
                qt_app.processEvents()
            except Exception:
                qt_app = None
    try:
        save_alongside = os.environ.get("SW2STEP_SAVE_ALONGSIDE", "0") == "1"
        step_path, status, note = sw2step.convert_single_for_freecad(
            src,
            use_cache=True,
            save_alongside=save_alongside,
            fast=True,
        )
        dt = time.time() - t0
        FreeCAD.Console.PrintMessage(
            f"[sw2step] Hoàn tất {src.name} -> {step_path.name} ({status}, {dt:.1f}s) {note}\\n"
        )
        return step_path
    finally:
        if qt_app:
            try:
                qt_app.restoreOverrideCursor()
            except Exception:
                pass


def open(filename: str):  # noqa: A001 - hàm chuẩn của FreeCAD Importer
    src = Path(filename).resolve()
    step_path = _convert_with_feedback(filename)
    return _load_step_into_doc(
        step_path, None, src.stem, src_path=src, is_drawing=(src.suffix.lower() == ".slddrw")
    )


def insert(filename: str, docname: str):
    src = Path(filename).resolve()
    step_path = _convert_with_feedback(filename)
    return _load_step_into_doc(
        step_path, docname, src.stem, src_path=src, is_drawing=(src.suffix.lower() == ".slddrw")
    )
'''


def get_freecad_mod_dirs() -> list[Path]:
    """Trả về danh sách các thư mục Mod của FreeCAD (hỗ trợ cả FreeCAD 0.20/0.21 và 1.0+)."""
    if "FreeCAD" in sys.modules:
        import FreeCAD  # type: ignore
        return [Path(FreeCAD.getUserAppDataDir()) / "Mod"]

    dirs: list[Path] = []
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        dirs.append(appdata / "FreeCAD" / "Mod")
        localapp = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        if (localapp / "FreeCAD").exists():
            dirs.append(localapp / "FreeCAD" / "Mod")
    elif sys.platform == "darwin":
        dirs.append(Path.home() / "Library" / "Application Support" / "FreeCAD" / "Mod")
    else:
        xdg = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        dirs.append(xdg / "FreeCAD" / "Mod")
        legacy = Path.home() / ".FreeCAD" / "Mod"
        if legacy.exists():
            dirs.append(legacy)
    return dirs


def install_freecad_plugin() -> list[Path]:
    """Cài đặt plugin SolidWorksImporter vào thư mục Mod của FreeCAD."""
    installed: list[Path] = []
    try:
        self_path = Path(__file__).resolve()
    except NameError as ex:
        raise RuntimeError("Không xác định được đường dẫn macro (__file__). "
                           "Hãy chạy: python sw2step.py --install-freecad") from ex
    for mod_root in get_freecad_mod_dirs():
        target = mod_root / "SolidWorksImporter"
        target.mkdir(parents=True, exist_ok=True)
        (target / "Init.py").write_text(_FREECAD_INIT_PY, encoding="utf-8")
        (target / "importSLD.py").write_text(_FREECAD_IMPORT_SLD_PY, encoding="utf-8")
        dst_script = target / "sw2step.py"
        if self_path != dst_script.resolve():
            shutil.copy2(self_path, dst_script)
        installed.append(target)
        log.info("Đã cài plugin FreeCAD tại: %s", target)
    return installed


def find_freecad_executable() -> str | None:
    """Tìm file thực thi của FreeCAD trên máy."""
    env_bin = os.environ.get("FREECAD_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin
    for name in ("freecad", "FreeCAD", "FreeCAD.exe"):
        w = shutil.which(name)
        if w:
            return w
    if os.name == "nt":
        roots = [
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs",
        ]
        hits: list[Path] = []
        for r in roots:
            if r.exists():
                hits.extend(sorted(r.glob("FreeCAD*/bin/FreeCAD.exe"), reverse=True))
                hits.extend(sorted(r.glob("FreeCAD*/bin/freecad.exe"), reverse=True))
        if hits:
            return str(hits[0])
    elif sys.platform == "darwin":
        mac_app = Path("/Applications/FreeCAD.app/Contents/MacOS/FreeCAD")
        if mac_app.exists():
            return str(mac_app)
    return None


def launch_in_freecad(files: list[Path]) -> int:
    """Mở danh sách file (STEP/DXF/SVG hoặc SLDPRT/SLDASM/SLDDRW) bằng FreeCAD."""
    exe = find_freecad_executable()
    if not exe:
        log.error("Không tìm thấy FreeCAD. Hãy đặt biến môi trường FREECAD_BIN hoặc mở từ trong FreeCAD.")
        return 1
    cmd = [exe] + [str(f.resolve()) for f in files]
    log.info("Đang mở trong FreeCAD: %s", " ".join(f.name for f in files))
    subprocess.Popen(cmd)
    return 0


def _run_inside_freecad_macro() -> None:
    """Khi người dùng chạy sw2step.py trực tiếp từ menu Macro của FreeCAD:
    1. Tự động cài plugin SolidWorksImporter vào FreeCAD Mod
    2. Đăng ký ngay định dạng .sldprt/.sldasm/.slddrw trong phiên FreeCAD hiện tại (không cần restart)
    3. Mở hộp thoại chọn file .SLDPRT/.SLDASM/.SLDDRW để mở ngay lập tức!"""
    import FreeCAD  # type: ignore

    targets = install_freecad_plugin()
    mod_dir = str(targets[0])
    if mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)
    for stale in ("importSLD", "sw2step"):
        sys.modules.pop(stale, None)
    FreeCAD.addImportType(
        "SolidWorks (*.sldprt *.sldasm *.slddrw *.SLDPRT *.SLDASM *.SLDDRW)", "importSLD"
    )
    FreeCAD.Console.PrintMessage(
        f"[sw2step] v{SW2STEP_VERSION}: đã cài đặt và kích hoạt bộ đọc SolidWorks tại: {mod_dir}\n"
        "[sw2step] Từ giờ bạn có thể bấm Ctrl+O hoặc kéo-thả trực tiếp file "
        ".SLDPRT / .SLDASM / .SLDDRW vào FreeCAD!\n"
    )
    if getattr(FreeCAD, "GuiUp", False):
        try:
            import importSLD  # type: ignore
            qfiledialog = None
            for mod_name in ("PySide", "PySide6", "PySide2"):
                try:
                    mod = __import__(mod_name)
                    w = getattr(mod, "QtWidgets", None) or getattr(mod, "QtGui", None)
                    if w and hasattr(w, "QFileDialog"):
                        qfiledialog = w.QFileDialog
                        break
                except Exception:
                    continue
            if qfiledialog:
                files, _ = qfiledialog.getOpenFileNames(
                    None,
                    "Chọn file SolidWorks (.SLDPRT / .SLDASM / .SLDDRW) để mở ngay",
                    str(Path.home()),
                    "SolidWorks (*.sldprt *.sldasm *.slddrw *.SLDPRT *.SLDASM *.SLDDRW);;All files (*.*)",
                )
                for f in files:
                    importSLD.open(f)
        except Exception as ex:
            FreeCAD.Console.PrintError(f"[sw2step] Lỗi khi mở file: {ex}\n")


# --------------------------------------------------------------------------- #
# Chạy CLI
# --------------------------------------------------------------------------- #
def _utf8_stdio() -> None:
    """Tránh UnicodeEncodeError khi log tiếng Việt bị chuyển hướng ra file/pipe trên Windows."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def write_report(path: Path, results: list[Result]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "output", "backend", "status", "seconds", "note"])
        for r in results:
            w.writerow([r.src, r.dst or "", r.backend, r.status, f"{r.seconds:.1f}", r.note])


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert SolidWorks .sldprt/.sldasm/.slddrw -> STEP/DXF/SVG & Open in FreeCAD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input", type=Path, nargs="*",
                    help="Một hoặc nhiều file/thư mục/wildcard chứa file SolidWorks")
    ap.add_argument("-o", "--output", type=Path, help="Thư mục xuất (mặc định: cạnh file gốc)")
    ap.add_argument("-r", "--recursive", action="store_true", help="Quét thư mục con")
    ap.add_argument("--backend", choices=["auto", "solidworks", "opensource"], default="auto")
    ap.add_argument("--setup", action="store_true",
                    help=f"Cài backend opensource vào {TOOLS_HOME}")
    ap.add_argument("--install-freecad", action="store_true",
                    help="Cài plugin vào FreeCAD để mở/kéo-thả trực tiếp file .SLDPRT/.SLDASM/.SLDDRW bằng Ctrl+O")
    ap.add_argument("--open", action="store_true",
                    help="Tự động mở ngay file kết quả trong FreeCAD sau khi chuyển đổi")
    ap.add_argument("--fast", action="store_true",
                    help="Ưu tiên tốc độ: bỏ qua bước kiểm tra/fallback phụ nếu sld2step đã tạo được khối 3D")
    ap.add_argument("--no-cache", action="store_true",
                    help="Không dùng bộ nhớ đệm (cache) cho các file đã chuyển đổi trước đó")
    ap.add_argument("--clear-cache", action="store_true",
                    help=f"Xoá toàn bộ cache STEP trong {CACHE_DIR}")
    ap.add_argument("--overwrite", action="store_true", help="Ghi đè file STEP đã có")
    ap.add_argument("--ext", choices=["step", "stp", "dxf", "svg"], default="step",
                    help="Định dạng xuất (mặc định: step; riêng .slddrw hỗ trợ thêm dxf, svg)")
    ap.add_argument("--sheet", type=int, default=None,
                    help="Chỉ xuất một tờ bản vẽ cụ thể (1, 2, ...) đối với file .slddrw nhiều tờ")
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="Số file xử lý song song (chỉ backend opensource; mỗi file tốn RAM/CPU)")
    ap.add_argument("--no-fallback", action="store_true",
                    help="opensource: không thử sldprt2step khi sld2step cho kết quả không hợp lệ")
    ap.add_argument("--fasteners", action="store_true",
                    help="opensource/assembly: sinh vít SHCS/BHCS đúng kích thước theo cấu hình")
    ap.add_argument("--asm-root", type=Path, action="append", default=[],
                    help="opensource/assembly: thư mục chứa part tham chiếu (lặp lại được)")
    ap.add_argument("--timeout", type=int, default=1800, help="Timeout mỗi file (giây)")
    ap.add_argument("--strict", action="store_true", help="Mã thoát 1 cả khi chỉ có WARN")
    ap.add_argument("--quit", action="store_true",
                    help="Đóng SolidWorks khi xong (nếu script tự mở nó)")
    ap.add_argument("--report", type=Path, help="Ghi báo cáo CSV")
    ap.add_argument("--log", type=Path, help="Ghi log ra file")
    ap.add_argument("--inspect", action="store_true",
                    help="Chẩn đoán .slddrw: liệt kê luồng dữ liệu, danh sách Sheet và các Layer giải mã được")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    _utf8_stdio()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", handlers=handlers)

    did_maintenance = False
    if args.clear_cache:
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
            log.info("Đã dọn sạch cache: %s", CACHE_DIR)
        did_maintenance = True

    if args.setup:
        try:
            rc = setup_opensource()
            if rc != 0:
                return rc
        except (subprocess.CalledProcessError, RuntimeError) as ex:
            log.error("Setup thất bại: %s", ex)
            return 1
        did_maintenance = True

    if args.install_freecad:
        install_freecad_plugin()
        if not opensource_ready() and not SolidWorksBackend.available():
            log.info("Lưu ý: Với file .SLDPRT/.SLDASM (khi không có SolidWorks), hãy chạy thêm: python %s --setup",
                     Path(__file__).name)
        did_maintenance = True

    if not args.input:
        if did_maintenance:
            return 0
        ap.error("thiếu đường dẫn input (hoặc dùng --setup / --install-freecad)")
    if args.jobs < 1:
        ap.error("--jobs phải >= 1")

    items = expand_inputs(args.input, args.recursive)
    if items is None:
        return 2
    jobs: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for item in items:
        root = item.resolve()
        if not root.exists():
            log.error("Không tồn tại: %s", root)
            return 2
        for f in collect_files(root, args.recursive):
            if f not in seen:
                seen.add(f)
                jobs.append((f, root if root.is_dir() else root.parent))
    if not jobs:
        log.error("Không có file .sldprt/.sldasm/.slddrw nào")
        return 2

    if args.inspect:
        for f, _ in jobs:
            if f.suffix.lower() == EXT_DRW:
                try:
                    inspect_slddrw(f)
                except Exception as ex:
                    print(f"== {f.name}: lỗi {type(ex).__name__}: {ex}")
        return 0

    has_non_drw = any(f.suffix.lower() != EXT_DRW for f, _ in jobs)
    has_drw = any(f.suffix.lower() == EXT_DRW for f, _ in jobs)

    chain: list = []
    sw_backend = None
    if args.backend in ("auto", "solidworks"):
        if SolidWorksBackend.available():
            try:
                sw_backend = SolidWorksBackend()
                chain.append(sw_backend)
            except Exception as ex:
                log.warning("Không khởi động được SolidWorks: %s", ex)
        elif args.backend == "solidworks" and has_non_drw:
            log.error("Không tìm thấy SolidWorks/pywin32 (cần Windows + pip install pywin32)")
            return 2
    if args.backend in ("auto", "opensource"):
        if opensource_ready():
            chain.append(OpenSourceBackend(args.timeout, not args.no_fallback,
                                           fast=args.fast or args.open))
        elif has_non_drw:
            if args.backend == "opensource":
                log.error("Backend opensource chưa cài. Chạy: python %s --setup", Path(__file__).name)
                return 2
            log.info("Backend opensource chưa cài (python %s --setup) - bỏ qua", Path(__file__).name)

    if has_drw and not any(isinstance(b, OpenSourceBackend) for b in chain):
        chain.append(BuiltinDrwBackend())

    if not chain:
        log.error("Không có backend khả dụng. Cài SolidWorks + pywin32, hoặc chạy --setup.")
        return 2

    n_workers = args.jobs
    if sw_backend and n_workers > 1:
        log.warning("SolidWorks COM chỉ chạy tuần tự -> bỏ qua --jobs")
        n_workers = 1
    dsts = plan_outputs(jobs, args.output, args.ext)
    total = len(jobs)
    log.info("%d file | backend: %s | song song: %d", total,
             " -> ".join(b.name for b in chain), n_workers)

    def process(i: int, f: Path, dst: Path) -> Result:
        tag = f"[{i}/{total}]"
        if dst.exists() and dst.stat().st_size > 0 and not args.overwrite:
            if dst.stat().st_mtime >= f.stat().st_mtime:
                log.info("%s bỏ qua (đã có & mới hơn file gốc): %s", tag, dst)
                return Result(f, dst, "-", "SKIP", "đã tồn tại")
        ext_key = dst.suffix.lstrip(".").lower()
        if not args.no_cache and not args.overwrite:
            cpath = cache_path_for(f, fasteners=args.fasteners, ext=ext_key, sheet_filter=args.sheet)
            if cpath.exists() and cpath.stat().st_size > 0:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cpath, dst)
                log.info("%s lấy nhanh từ cache: %s", tag, dst.name)
                return Result(f, dst, "cache", "OK", "lấy từ cache", 0.0)
        res = Result(f, None, "-", "FAIL", "không có backend nào xử lý được")
        t0 = time.time()
        for b in chain:
            try:
                status, note = b.convert(f, dst, fasteners=args.fasteners,
                                         asm_roots=args.asm_root, sheet_filter=args.sheet)
            except Exception as ex:
                log.debug("backend %s lỗi", b.name, exc_info=True)
                status, note = "FAIL", f"{type(ex).__name__}: {ex}"
            res = Result(f, dst if status != "FAIL" else None, b.name, status, note,
                         time.time() - t0)
            if status != "FAIL":
                if not args.no_cache and dst.exists() and dst.stat().st_size > 0:
                    try:
                        shutil.copy2(
                            dst,
                            cache_path_for(f, fasteners=args.fasteners, ext=ext_key, sheet_filter=args.sheet),
                        )
                    except OSError:
                        pass
                break
            log.warning("%s %s: backend %s thất bại (%s)", tag, f.name, b.name, note)
        lvl = {"OK": logging.INFO, "WARN": logging.WARNING, "FAIL": logging.ERROR}[res.status]
        log.log(lvl, "%s %-4s %s [%s, %.1fs] %s", tag, res.status, f.name,
                res.backend, res.seconds, res.note)
        return res

    results: list[Result] = []
    interrupted = False
    try:
        if n_workers == 1:
            for i, ((f, _), dst) in enumerate(zip(jobs, dsts), 1):
                results.append(process(i, f, dst))
        else:
            ex = ThreadPoolExecutor(max_workers=n_workers)
            try:
                futs = [ex.submit(process, i, f, dst)
                        for i, ((f, _), dst) in enumerate(zip(jobs, dsts), 1)]
                results = [fu.result() for fu in futs]
            finally:
                ex.shutdown(wait=False, cancel_futures=True)
    except KeyboardInterrupt:
        interrupted = True
        kill_all_children()
        log.warning("Đã dừng theo yêu cầu (Ctrl+C); kết quả đã xong được giữ lại")
    finally:
        if sw_backend:
            sw_backend.close(args.quit)
        if args.report:
            write_report(args.report, results)

    n = {k: sum(r.status == k for r in results) for k in ("OK", "WARN", "FAIL", "SKIP")}
    log.info("Xong: %d OK, %d WARN (nên kiểm tra trong FreeCAD), %d lỗi, %d bỏ qua",
             n["OK"], n["WARN"], n["FAIL"], n["SKIP"])
    for r in results:
        if r.status in ("WARN", "FAIL"):
            log.log(logging.ERROR if r.status == "FAIL" else logging.WARNING,
                    "  %-4s %s: %s", r.status, r.src.name, r.note)

    if args.open and not interrupted:
        ready_files = [r.dst for r in results if r.dst and r.dst.exists()]
        if ready_files:
            launch_in_freecad(ready_files)

    if interrupted:
        return 130
    return 1 if (n["FAIL"] or (args.strict and n["WARN"])) else 0


if __name__ == "__main__":
    if "FreeCAD" in sys.modules and len(sys.argv) <= 1:
        _run_inside_freecad_macro()
    else:
        sys.exit(main())
# Technical Documentation & Binary Format Specification (`DOCS_TECHNICAL_en.md`)

This document provides in-depth technical details on the architecture of `sw2step.py` (version `2026.10.22-v3`), including backend orchestration for `.SLDPRT` / `.SLDASM` and binary reverse-engineering specifications for the SolidWorks 2015+ `GContainer` archive format and `.SLDDRW` 2D technical drawing streams.

## 1. System Architecture

`sw2step.py` implements a hybrid pipeline composed of three distinct conversion engines:

| Engine | Target Formats | Implementation Details |
| :--- | :--- | :--- |
| **`OpenSourceBackend`** | `.SLDPRT`, `.SLDASM` | Executes [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step) to extract Parasolid XT streams and synthesize B-rep solids via [CadQuery/OCP](https://github.com/cadquery/OCP). If solid geometry contains defects, it runs [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step) as a fallback, performs comparative geometric analysis (`BRepCheck_Analyzer`), selects the optimal result, and injects STEP AP214 colors (`inject_step_ap214_colors`). |
| **`BuiltinDrwBackend`** | `.SLDDRW` | Decodes drawings directly using **pure Python** standard library modules (`unpack_sld_gcontainer` $\rightarrow$ `parse_slddrw_geometry` $\rightarrow$ `write_slddrw_step` / `write_slddrw_dxf` / `write_slddrw_svg`). Operates without virtual environments or external binary libraries. |
| **`SolidWorksBackend`** | `.SLDPRT`, `.SLDASM`, `.SLDDRW` | Automates local SolidWorks via COM (`SldWorks.Application` on Windows). When converting `.SLDDRW` to `.STEP`, it delegates to `BuiltinDrwBackend` because native SolidWorks `SaveAs3` cannot export 2D drawings to ISO STEP. |

## 2. SolidWorks 2015+ `GContainer` Format Specification

Beginning with SolidWorks 2015, the traditional OLE2 Compound Document format (`D0 CF 11 E0...`) was replaced with a proprietary compressed archive format designated as **`GContainer`**.

### 2.1. Block Marker Synchronization (`_BLOCK_MARKER`)

* The first 4 bytes of a `GContainer` file do not constitute a fixed magic signature (varying across files, e.g., `04 63 32 5b` or `1e 4d 27 95`), and the pre-entry header length ranges between 18 and 20 bytes.
* `unpack_sld_gcontainer()` locates the first entry by searching for the 6-byte marker `_BLOCK_MARKER = b"\x14\x00\x06\x00\x08\x00"`, corresponding to `ver1 = 6`, `ver2 = 8` positioned at byte offset `+2` within each entry header.

### 2.2. Stream Entry Header Structure (28 Bytes)

Each stream entry begins 2 bytes prior to the block marker and is structured as `<IHHIIIII` (28 bytes, little-endian):

| Byte Offset | Type | Field Identifier | Description |
| :--- | :--- | :--- | :--- |
| `+0` | `uint32` | `u0` | Block flag / identifier (upper 2 bytes are consistently `0x0014`). |
| `+4` | `uint16` | `ver1` | Version major (consistently `6` / `0x0006`). |
| `+6` | `uint16` | `ver2` | Version minor (consistently `8` / `0x0008`). |
| `+8` | `uint32` | `ts` | Unix creation / modification timestamp. |
| `+12` | `uint32` | `crc` | `CRC32` checksum of the uncompressed stream data. |
| `+16` | `uint32` | `csize` | Compressed stream payload size in bytes. |
| `+20` | `uint32` | `usize` | Uncompressed stream payload size in bytes. |
| `+24` | `uint32` | `name_len` | Stream name length in bytes. |
| `+28` | `bytes[name_len]` | `raw_name` | Nibble-swapped stream name string. |

* **Stream Name Decoding (`_swap_nibbles`)**: Every byte `x` in `raw_name` has its upper and lower 4-bit nibbles swapped: `((x >> 4) | ((x & 0x0F) << 4))`. Decoding the transformed bytes as UTF-8 yields canonical stream identifiers, such as `Contents/DisplayLists`, `Contents/VBLists`, `SheetPreviews/SheetNames`, and `ImportedComp/...`.
* **Payload Decompression**: The payload of length `csize` following the stream name is compressed using **Raw Deflate** (without zlib or gzip wrappers). It is decompressed via `zlib.decompress(chunk, -15)` and verified against `usize` and `crc`.

## 3. Decoding 2D Geometry & 3D Model in `.SLDDRW`

A `.SLDDRW` drawing archive encapsulates graphics data across three core streams:
1. **`SheetPreviews/SheetNames`** and **`Images/Sheet_*`**: Declares sheet counts and names (`Sheet1`, `Sheet2`, etc.).
2. **`Contents/DisplayLists`**: Encodes drawing border lines, title block geometry, dimension leaders, arrows, text entities, and drawing view projection matrices.
3. **`Contents/VBLists`**: Stores 3D edge curve buckets (`uiViewBucket_c`), 3D tessellated manifold faces (`uoTempFaceTessData_c`), and material property blocks (`uoBodyPropInfo_c`, `moVisualProperties_c`).

### 3.1. DisplayList Graphic Record Opcodes

Geometric records in `DisplayLists` are preceded by a header pair `<II` denoting `(record_size, opcode)`, with spatial coordinates encoded as 64-bit IEEE double-precision floats in **meters**:

| `record_size` | `opcode` | Payload Definition | Geometric Entity |
| :--- | :--- | :--- | :--- |
| `0x50` (80B) | `0x04` | `<6d` at offset `+8`: $(x_1, y_1, z_1, x_2, y_2, z_2)$ | Linear segment (sheet border, table grid, dimension extension, or leader). |
| `0x78` (120B) | `0x06` | `<II` at `+8` (`u1`, `npts=3`) + `<9d` at `+16`: 3 vertices $(x, y, z)$ | Solid triangular dimension arrowhead. |
| `0x80` (128B) | `0x02` | `<9d` at `+8`: start $(x_1, y_1, z_1)$, end $(x_2, y_2, z_2)$, center $(x_c, y_c, z_c)$ | Full circle (if endpoints coincide within `0.05mm`) or circular arc (`ARC`). |
| `0x6C` (108B) | `0x0A` | `<dI` at `+8`: `(height_m: double, point_size: uint32)` | Font sizing record preceding one or more text elements. |
| `0x50..0x1000` | `0x12` | `<5d` at `pos - 40`: $(x, y, z, d_x, d_y)$ with UTF-16LE text after `\xff\xfe\xff` | 2D Text string (if $|d_x| > 10^{10}$, text is rotated vertically by $90^\circ$). |

### 3.2. Coordinate Depth Separation ($Z \approx 0$ vs. $Z \neq 0$)

In `Contents/DisplayLists`, entities belonging to the paper sheet are decoupled from view-attached annotations by their coordinate depth ($Z$):
* **Border & Title Block Entities (`01_Khung_Ban_Ve`, `04_Chu_Ghi_Chu`)**: Positioned at $|z| \le 10^{-6}\text{ m}$ ($z = 0.0$).
* **View-Attached Dimensions (`03_Kich_Thuoc`)**: Positioned at $|z| > 10^{-6}\text{ m}$ (corresponding to the focal depth of the drawing view plane).

This geometric invariant allows `sw2step.py` to deterministically segregate border geometry from dimension leaders and title block notes from dimension numbers.

### 3.3. Multi-Sheet Detection & Offset Scheduling

In multi-sheet drawings, entities in `Contents/DisplayLists` are serialized in sequential blocks:
1. Border geometry and title block notes for sheet $k$ (at $z = 0$).
2. Drawing view headers (`view_hdr`) and dimensions for sheet $k$ (at $z \neq 0$).

When `SheetPreviews/SheetNames` defines $N > 1$ sheets, the parser identifies sheet boundaries: once view entities for the active sheet have been processed, the occurrence of $\ge 8$ consecutive $z = 0$ border segments signals the inception of sheet $k + 1$. Each sheet $k$ is assigned a horizontal displacement `offset_x_mm = k * (sheet_width_mm + 50.0)`, laying out all sheets side-by-side without overlap.

### 3.4. Drawing View Transformation & 3D Normal Vector Matching

Each 2D drawing view is defined by a 44-byte record header (`3c 00 00 00 09 00 ...`), followed by:
* Rotation matrix flag `flag` (1 byte): if `flag == 0`, rotation matrix $R = I_3$; if `flag != 0`, 72 bytes follow containing a column-major $3 \times 3$ orthogonal matrix:
  $$x_{\text{sheet}} = c_x + o_x + s \cdot (r_0 x + r_3 y + r_6 z)$$
  $$y_{\text{sheet}} = c_y + o_y + s \cdot (r_1 x + r_4 y + r_7 z)$$
  where $s$ denotes view scale, $(o_x, o_y, o_z)$ denotes model center offset, and $(c_x, c_y, c_z)$ denotes the view center on the sheet (in meters).
* The third column of the rotation matrix $\vec{v}_z = (r_2, r_5, r_8)$ represents the **3D line-of-sight normal vector**. `sw2step.py` extracts the normal vector at the header of each `uiViewBucket_c` in `Contents/VBLists` and selects the bucket with $|\vec{v}_z \cdot \vec{n}_{\text{bucket}}| > 0.95$, ensuring that each view maps to its corresponding 3D edge silhouette.

## 4. SolidWorks Material Color Decoding & STEP AP214 Injection

### 4.1. Binary Color Offsets in Container Streams

`extract_sld_colors()` scans two binary structures across `Contents/VBLists` and `Contents/DisplayLists`:
1. **`uoBodyPropInfo_c`**: Stores body-specific material properties (e.g. `SolidWorks Materials|5052-H34`). Located 22 bytes after the marker sequence `\x0e\x80\x00\x00\x00\x00` + 16 bytes of `0xFF` is a 4-byte sequence `R G B 00`.
2. **`moVisualProperties_c`**: Located at byte offset `+36` after the string `moVisualProperties_c` is a 4-byte sequence `R G B 00` representing visual component appearance.

### 4.2. STEP AP214 Entity Hierarchy

To preserve distinct visual styles in [FreeCAD](https://github.com/freecad/freecad) (`ImportGui`) and third-party CAD applications, `sw2step.py` writes standard **ISO 10303-214 (`AUTOMOTIVE_DESIGN`)** styling entities:

* **2D Layer Curve Styling (`GEOMETRIC_CURVE_SET`)**:
  ```step
  #10 = DRAUGHTING_PRE_DEFINED_CURVE_FONT('continuous');
  #11 = COLOUR_RGB('', 0.0000, 0.3500, 0.8000);
  #12 = CURVE_STYLE('', #10, POSITIVE_LENGTH_MEASURE(0.18), #11);
  #13 = PRESENTATION_STYLE_ASSIGNMENT((#12));
  #14 = STYLED_ITEM('', (#13), #CurveSetID);
  ```
* **3D Solid Body Styling (`MANIFOLD_SOLID_BREP` / `SHELL_BASED_SURFACE_MODEL`)**:
  ```step
  #20 = COLOUR_RGB('', 0.7600, 0.7800, 0.8000);
  #21 = FILL_AREA_STYLE_COLOUR('', #20);
  #22 = FILL_AREA_STYLE('', (#21));
  #23 = SURFACE_STYLE_FILL_AREA(#22);
  #24 = SURFACE_SIDE_STYLE('', (#23));
  #25 = SURFACE_STYLE_USAGE(.BOTH., #24);
  #26 = PRESENTATION_STYLE_ASSIGNMENT((#25));
  #27 = STYLED_ITEM('', (#26), #SolidOrShellID);
  ```
* All `#STYLED_ITEM` records are bound to the document representation via `MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('', (#14, #27, ...), #GeomContextID)`.

## 5. References & Community Acknowledgments

* [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step) — Parasolid XT extraction, assembly component transformation, and fastener generation.
* [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step) — Standalone `.SLDPRT` B-rep solid reconstruction and ISO 10303-21 STEP output.
* [CadQuery/OCP](https://github.com/cadquery/OCP) — Python bindings for OpenCASCADE Technology (OCCT).
* [FreeCAD Core Source](https://github.com/freecad/freecad) — Modular import architecture (`FreeCAD.addImportType`, `ImportGui`, and `TechDraw` workbench).

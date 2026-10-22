# sw2step — Native SolidWorks (.SLDPRT / .SLDASM / .SLDDRW) Converter & Direct Importer for FreeCAD






**sw2step** is a high-performance command-line utility and native importer plugin for [FreeCAD](https://github.com/freecad/freecad). It enables seamless opening and conversion of all three core SolidWorks formats (`.SLDPRT`, `.SLDASM`, and `.SLDDRW`) into **STEP AP214 (`.step` / `.stp`)**, **AutoCAD DXF (`.dxf`)**, and **Scalable Vector Graphics (`.svg`)** without requiring a local SolidWorks installation.

## 1. Key Capabilities

| SolidWorks File Type | Conversion Pipeline in `sw2step.py` (v3) | Supported Outputs |
| :--- | :--- | :--- |
| **`.SLDPRT`** (3D Part) | Extracts B-rep solid bodies from native Parasolid XT data using [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step) and automated geometric validation / fallback with [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step). Extracts material and body colors from internal `uoBodyPropInfo_c` and `moVisualProperties_c` records to inject full **STEP AP214** styling (`STYLED_ITEM`, `SURFACE_STYLE_USAGE`, `COLOUR_RGB`). | `.step`, `.stp` |
| **`.SLDASM`** (3D Assembly) | Reconstructs 3D component trees, automatically unpacks embedded parts from `ImportedComp/*` sub-streams, synthesizes standard socket head fasteners (`--fasteners`), and preserves individual component transformations and body appearances. | `.step`, `.stp` |
| **`.SLDDRW`** (2D Drawing) | Decodes native SolidWorks 2015+ `GContainer` compound archives using pure Python standard library modules (zero external binary dependencies): supports **multi-sheet drawings**, separates geometry into **5 toggleable CAD layers**, renders crisp **95-glyph vector proportional typography**, and embeds full colored **3D model geometry**. | `.step`, `.stp`, `.dxf`, `.svg` |

### What's New in Version `2026.10.22-v3`

* **Multi-Sheet Technical Drawing Support**: Automatically reads sheet names from `SheetPreviews/SheetNames` and `Images/Sheet_*`, identifies sheet transition boundaries in `Contents/DisplayLists`, and arranges multiple sheets side-by-side with a `50mm` margin (`offset_x = k * (sheet_width + 50.0)`) to eliminate overlapping at origin $(0, 0)$. Individual sheets can also be exported with `--sheet <N>`.
* **5 Structured CAD Layers**: Automatically categorizes entities based on coordinate depth ($Z \approx 0$ for sheet title blocks and $|Z| > 10^{-6}\text{ m}$ for drawing view-attached dimensions) across STEP, DXF, SVG, and FreeCAD:
  * `01_Khung_Ban_Ve` (Border & Title Block)
  * `02_Hinh_Chieu` (Projected 2D Views)
  * `03_Kich_Thuoc` (Dimensions, Leaders & Filled Arrowheads)
  * `04_Chu_Ghi_Chu` (Title Block Labels & Text Notes)
  * `05_Model_3D` (Embedded 3D B-rep Model with Material Color)
* **Smooth 95-Glyph Proportional CAD Vector Font**: Replaces blocky uppercase stroke fonts with a smooth 95-character proportional vector font supporting lowercase `a-z` (with descenders for `g, j, p, q, y`), multi-segment curves (12–14 chords per curve), exact point sizes (`pt_size` decoded from opcode `0x0A`), and comprehensive mechanical symbols (`Ø`, `ø`, `⌀`, `±`, `°`, `×`, `≤`, `≥`, `µ`, `⊥`, `∥`, `⌖`, `⌴`, `⌵`, `↧`, `△`, `□`), translating SolidWorks tags (`<MOD-DIAM>`, `<MOD-PM>`, `<MOD-DEG>`, `<MOD-DEPTH>`, etc.) automatically.
* **Direct 2D Presentation in FreeCAD**: When opening `.SLDDRW` files in [FreeCAD](https://github.com/freecad/freecad), the plugin automatically groups 2D layers into an `App::DocumentObjectGroup`, hides `05_Model_3D` by default (`Visibility = False`) to give an unobstructed flat 2D top view, and synthesizes a native **`TechDraw::DrawPage`** with a 1:1 SVG symbol for direct viewing, printing, and PDF export.
* **Deterministic SHA-256 Cache Engine**: Computes composite hashes over file contents, timestamps, and version tags to store converted deliverables in `~/.sw2step/cache`, accelerating repeated loads inside FreeCAD to under `0.1s`.

## 2. Structured 5-Layer Organization

When opening `.SLDDRW` drawings or inspecting generated `.step` / `.dxf` / `.svg` files, entities are arranged into 5 distinct layers that can be toggled on and off with a single tap of the **Spacebar** in the FreeCAD tree:

| Layer / Product Name | Geometric Contents | Default Color Scheme | Initial FreeCAD State |
| :--- | :--- | :--- | :--- |
| **`01_Khung_Ban_Ve`** | Standard sheet borders (A0–A4), title blocks, bill of materials tables, projection angle symbols. | Dark Gray (`#404040` / ACI 7) | Visible (`Visibility = True`) |
| **`02_Hinh_Chieu`** | Projected 2D visible and section view outlines. | Solid Black (`#141414` / ACI 7) | Visible (`Visibility = True`) |
| **`03_Kich_Thuoc`** | Extension lines, dimension lines, filled triangular arrowheads (`opcode 0x06`), leaders, and dimension values (`100`, `Ø...`). | Engineering Blue (`#0059CC` / ACI 5) | Visible (`Visibility = True`) |
| **`04_Chu_Ghi_Chu`** | Title block textual attributes, technical notes, tolerance specifications, and manufacturing guidelines. | Deep Forest Green (`#126138` / ACI 3) | Visible (`Visibility = True`) |
| **`05_Model_3D`** | Embedded 3D B-rep manifold faces (`SHELL_BASED_SURFACE_MODEL`) and wireframe boundary curves. | Native SolidWorks Material RGB | **Hidden by default (`Visibility = False`)** for clean 2D viewing; select and press Spacebar to view 3D |

Multi-sheet drawings prefix each layer with the sheet name (e.g. `Sheet1_01_Khung_Ban_Ve`, `Sheet2_01_Khung_Ban_Ve`) and generate independent `TechDraw::DrawPage` sheets (`Ban_Ve_2D_Sheet1`, `Ban_Ve_2D_Sheet2`).

## 3. Installation Guide

### System Requirements

* **2D Drawings (`.SLDDRW`)**: Requires standard [Python](https://www.python.org/) 3.10 or newer. Runs out-of-the-box on Windows, Linux, and macOS using only standard library modules (no third-party dependencies required).
* **3D Parts and Assemblies (`.SLDPRT`, `.SLDASM`)**:
  * **Open-Source Mode (No SolidWorks required)**: Requires 64-bit [Python](https://www.python.org/) 3.10–3.14 and Git. Running `--setup` automatically configures a self-contained virtual environment in `~/.sw2step/venv` containing [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step), [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step), `sldprt2xt`, and [CadQuery/OCP](https://github.com/cadquery/OCP).
  * **SolidWorks COM Mode (Optional on Windows with SolidWorks)**: Uses local SolidWorks installation via `pip install pywin32`.

### Method A: One-Click Setup Inside FreeCAD GUI (Recommended)

1. Launch [FreeCAD](https://www.freecad.org/downloads.php), then navigate to **Macro** $\rightarrow$ **Macros...** in the menu bar.
2. Click **...** next to *User macros location* (or copy `sw2step.py` to that directory), select **`sw2step.py`**, and click **Execute**.
3. The script will:
   * Install the `SolidWorksImporter` plugin (`Init.py`, `importSLD.py`, `sw2step.py`) into your FreeCAD `Mod` directory.
   * Register the importer dynamically in the current session **without requiring a FreeCAD restart**.
   * Open a file dialog so you can immediately choose a `.SLDPRT`, `.SLDASM`, or `.SLDDRW` file to open.

### Method B: Terminal / Command Prompt Installation

```bash
# Install complete open-source backends (for 3D parts/assemblies) and install the FreeCAD plugin
python sw2step.py --setup --install-freecad

# Or install only the FreeCAD plugin (for immediate 2D .SLDDRW opening via pure Python)
python sw2step.py --install-freecad
```

Once installed, SolidWorks files can be opened in FreeCAD via:
* **`Ctrl + O`** (`File` $\rightarrow$ `Open`) or `File` $\rightarrow$ `Import`.
* **Drag-and-Drop** directly into the FreeCAD 3D viewport.
* Right-clicking the file in file explorer $\rightarrow$ **Open with** $\rightarrow$ **FreeCAD**.

## 4. Command-Line Interface (CLI Reference)

### Common Examples

```bash
# 1. Convert a 2D drawing to STEP and immediately inspect in FreeCAD
python sw2step.py 2.SLDDRW --open

# 2. Export 2D drawing to layered AutoCAD DXF or scaled 1:1 SVG
python sw2step.py 2.SLDDRW --ext dxf
python sw2step.py 2.SLDDRW --ext svg

# 3. Export only Sheet 1 from a multi-sheet drawing
python sw2step.py Assembly_Drawings.SLDDRW --ext dxf --sheet 1

# 4. Diagnose internal drawing streams, sheet names, layer metrics, and color palettes
python sw2step.py 2.SLDDRW --inspect

# 5. Convert 3D parts or assemblies with fastener generation and open in FreeCAD
python sw2step.py bracket.SLDPRT --open
python sw2step.py gearbox.SLDASM --fasteners --open

# 6. Batch convert an entire folder recursively with 4 worker threads and CSV reporting
python sw2step.py "D:\SolidWorks_Vault" -r -o "D:\STEP_Library" --jobs 4 --report report.csv
```

### Full Argument Reference

| Option | Description |
| :--- | :--- |
| `input` | One or more input paths, directory roots, or wildcards (`*.sldprt`, `*.slddrw`). |
| `-o`, `--output <DIR>` | Target output directory (defaults to the directory alongside the source file). |
| `-r`, `--recursive` | Recursively search subdirectories for matching SolidWorks files. |
| `--ext {step,stp,dxf,svg}` | Target export format (defaults to `step`; `dxf` and `svg` are supported for `.slddrw`). |
| `--sheet <N>` | Select a specific sheet number (`1`, `2`, ...) for multi-sheet drawing files. |
| `--open` | Automatically launch FreeCAD and load the converted deliverables upon completion. |
| `--inspect` | Print container diagnostics: stream sizes, sheet names, layer object counts, and body colors. |
| `--backend {auto,solidworks,opensource}` | Conversion backend preference (`auto` prioritizes SolidWorks COM if installed, then `opensource`). |
| `--setup` | Clone and configure the open-source pipeline into `~/.sw2step`. |
| `--install-freecad` | Install or update the `SolidWorksImporter` extension in the FreeCAD `Mod` folder. |
| `--fast` | Fast-path for `.sldprt`: bypass secondary validation if `sld2step` outputs a solid B-rep. |
| `--no-fallback` | Disable fallback to `sldprt2step` when `sld2step` reports shape warnings. |
| `--fasteners` | Generate accurate 3D geometry for standard hex and socket head screws in assemblies. |
| `--asm-root <DIR>` | Additional search directory for external assembly components (can be specified multiple times). |
| `-j`, `--jobs <N>` | Number of concurrent conversion workers (applicable to the `opensource` backend). |
| `--overwrite` | Overwrite existing output files even if they are newer than the source file. |
| `--no-cache` | Bypass the local cache and force re-conversion. |
| `--clear-cache` | Clear all cached STEP files in `~/.sw2step/cache`. |
| `--report <FILE.csv>` | Write a comprehensive CSV summary with conversion status, durations, and notes (UTF-8 BOM). |

### Environment Variables

* `SW2STEP_HOME`: Custom directory for storing external tools and cache (defaults to `~/.sw2step`).
* `SW2STEP_SAVE_ALONGSIDE=1`: When opening in FreeCAD, saves `.step` files alongside the original SolidWorks files rather than inside the user cache directory.
* `FREECAD_BIN`: Explicit path to the FreeCAD executable (`FreeCAD.exe` / `freecad`).

## 5. Acknowledgments & Credits

This project builds upon the reverse-engineering insights and open-source tooling created by the open CAD/CAE community. Sincere gratitude is extended to the following authors and projects:

* [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step) by **dsandall**: The foundational open-source converter for `.SLDPRT` and `.SLDASM` files, providing Parasolid XT stream extraction, assembly coordinate transformation resolution, fastener synthesis, and robust patches for `sldprt2xt`.
* [**BlinkingSun/sldprt2step**](https://github.com/BlinkingSun/sldprt2step) by [**BlinkingSun**](https://github.com/BlinkingSun): An independent `.SLDPRT`-to-STEP conversion utility providing vital validation checks and solid fallback capabilities for complex geometry.
* **`sldprt2xt`**: Low-level stream extractor for unpacking SolidWorks compound document containers.
* [**CadQuery / OCP**](https://github.com/cadquery/OCP) and [**CadQuery/ocp-build-system**](https://github.com/CadQuery/ocp-build-system): Python bindings for the OpenCASCADE Technology (OCCT) geometric modeling kernel, providing B-rep validation (`BRepCheck_Analyzer`), mass property evaluation (`BRepGProp`), and STEP translation.
* [**FreeCAD**](https://github.com/freecad/freecad): The open-source parametric 3D modeler whose modular architecture (`FreeCAD.addImportType`, `ImportGui`, and `TechDraw` workbench) made native SolidWorks import workflows possible.

## 6. Technical Documentation & Contributing

* For in-depth reverse-engineering documentation on the SolidWorks 2015+ `GContainer` archive format, `Contents/DisplayLists` opcodes, view projection matrices, $Z$-depth layer separation, and STEP AP214 color injection, refer to **`DOCS_TECHNICAL_en.md`**.
* Contributions, bug reports, and test files (particularly multi-sheet drawings and multi-body parts) are warmly welcomed via GitHub Issues and Pull Requests.

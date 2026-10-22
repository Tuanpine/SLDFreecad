# sw2step — Công cụ chuyển đổi & Mở trực tiếp SolidWorks (.SLDPRT / .SLDASM / .SLDDRW) trong FreeCAD






**sw2step** là công cụ dòng lệnh (CLI) kiêm plugin tích hợp trực tiếp cho [FreeCAD](https://github.com/freecad/freecad), giúp mở và chuyển đổi cả 3 định dạng gốc của SolidWorks (`.SLDPRT`, `.SLDASM`, `.SLDDRW`) sang chuẩn **STEP AP214 (`.step` / `.stp`)**, **AutoCAD DXF (`.dxf`)** và **Vector SVG (`.svg`)** mà không bắt buộc phải cài đặt SolidWorks trên máy.

> **English Summary:** `sw2step.py` is an all-in-one SolidWorks-to-STEP/DXF/SVG converter and native [FreeCAD](https://github.com/freecad/freecad) importer plugin. It converts 3D Parts (`.SLDPRT`), 3D Assemblies (`.SLDASM` including embedded `ImportedComp/*` components), and 2D Technical Drawings (`.SLDDRW` with multi-sheet layout, 5 toggleable layers, proportional CAD typography, and STEP AP214 RGB colors) using either an open-source Python pipeline or SolidWorks COM automation.

## 1. Tính năng nổi bật (Key Features)

| Định dạng | Khả năng xử lý trong `sw2step.py` (v3) | Định dạng xuất |
| :--- | :--- | :--- |
| **`.SLDPRT`** (3D Part) | Trích xuất khối rắn B-rep từ luồng Parasolid XT thông qua [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step) và đối chiếu/fallback tự động với [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step); tự động đọc màu vật liệu/body từ `uoBodyPropInfo_c` và `moVisualProperties_c` để gắn màu chuẩn **STEP AP214** (`STYLED_ITEM` / `COLOUR_RGB`). | `.step`, `.stp` |
| **`.SLDASM`** (3D Assembly) | Tái tạo cây lắp ghép 3D, tự động giải nén các chi tiết nhúng sẵn trong luồng `ImportedComp/*`, hỗ trợ sinh ốc vít tiêu chuẩn (`--fasteners`) và bảo toàn màu sắc từng chi tiết. | `.step`, `.stp` |
| **`.SLDDRW`** (2D Drawing) | Giải mã trực tiếp container `GContainer` (SolidWorks 2015+) bằng **thuần Python** (không cần cài thêm thư viện ngoài): hỗ trợ **bản vẽ nhiều tờ (Multi-Sheet)**, tách sẵn **5 Layer kỹ thuật**, bộ **font vector CAD 95 ký tự** nét mượt và nhúng kèm **mô hình 3D** có màu. | `.step`, `.stp`, `.dxf`, `.svg` |

### Điểm mới trong phiên bản `2026.10.22-v3`

* **Hỗ trợ bản vẽ nhiều tờ (Multi-Sheet Drawings)**: Tự động giải mã danh sách tờ từ `SheetPreviews/SheetNames` và `Images/Sheet_*`, phát hiện ranh giới chuyển tờ trong `Contents/DisplayLists` và dàn hàng ngang các tờ cách nhau `50mm` (`offset_x = k * (sheet_width + 50)`), đảm bảo các tờ không bao giờ bị vẽ đè lên nhau tại gốc $(0, 0)$. Hỗ trợ cờ `--sheet <N>` để xuất riêng 1 tờ bất kỳ.
* **Phân lớp 5 Layer chuẩn kỹ thuật (Toggleable 2D/3D Layers)**: Tự động bóc tách các thành phần trong bản vẽ `.SLDDRW` dựa trên độ sâu toạ độ $Z$ (`abs(z) <= 1e-6` cho khung bản vẽ/khung tên và `abs(z) > 1e-6` cho kích thước gắn với hình chiếu) thành 5 lớp độc lập có tên và màu riêng trên cả STEP, DXF, SVG và FreeCAD.
* **Bộ font vector CAD tỷ lệ biến thiên 95 ký tự**: Hỗ trợ đầy đủ chữ hoa `A-Z`, chữ thường `a-z` (có chân chữ `g, j, p, q, y`), chữ số `0-9` bo tròn mượt và trọn bộ ký hiệu cơ khí (`Ø`, `ø`, `⌀`, `±`, `°`, `×`, `≤`, `≥`, `µ`, `⊥`, `∥`, `⌖`, `⌴`, `⌵`, `↧`, `△`, `□`). Tự động chuyển đổi các thẻ nội bộ của SolidWorks (`<MOD-DIAM>`, `<MOD-PM>`, `<MOD-DEG>`, `<MOD-DEPTH>`, `<MOD-CBORE>`, `<MOD-CSINK>`) và đọc chính xác cỡ chữ `pt` từ bản ghi `op == 0x0a`.
* **Mở thẳng dạng bản vẽ 2D trong FreeCAD**: Khi mở `.SLDDRW` trong [FreeCAD](https://github.com/freecad/freecad), plugin tự động gom nhóm 4 Layer 2D, **ẩn mặc định lớp `05_Model_3D`** để khung nhìn `Top View` hiển thị thuần bản vẽ 2D phẳng (có thể bật lại khối 3D bất cứ lúc nào bằng phím `Space`), đồng thời tự tạo trang bản vẽ 2D gốc **`TechDraw::DrawPage`** cho từng tờ.
* **Bộ nhớ đệm thông minh (SHA-256 Content & Timestamp Cache)**: Lưu kết quả chuyển đổi tại `~/.sw2step/cache` kèm mã phiên bản `SW2STEP_VERSION`, giúp lần mở thứ hai trong FreeCAD diễn ra tức thì (dưới `0.1s`) và tự động làm mới khi file gốc hoặc script thay đổi.

## 2. Cấu trúc 5 Layer khi mở bản vẽ `.SLDDRW`

Khi mở trực tiếp file `.SLDDRW` trong FreeCAD hoặc mở file `.step` / `.dxf` / `.svg` xuất ra, cấu trúc bản vẽ được chia thành 5 lớp rõ ràng để bạn bấm phím **`Space`** bật/tắt từng phần:

| Tên Layer / Product | Nội dung hình học | Màu sắc mặc định | Trạng thái khi mở trong FreeCAD |
| :--- | :--- | :--- | :--- |
| **`01_Khung_Ban_Ve`** | Khung giấy tiêu chuẩn (A0–A4), khung tên, bảng kê vật tư (BOM), vòng tròn ký hiệu góc chiếu. | Xám đậm (`#404040` / ACI 7) | Hiển thị (`Visibility = True`) |
| **`02_Hinh_Chieu`** | Đường nét các hình chiếu 2D (chiếu đứng, chiếu bằng, chiếu cạnh, hình cắt, trục đo). | Đen nét dày (`#141414` / ACI 7) | Hiển thị (`Visibility = True`) |
| **`03_Kich_Thuoc`** | Đường gióng, đường kích thước, mũi tên tam giác đặc (`op == 6`), đường dẫn và chữ số kích thước (`100`, `Ø...`). | Xanh dương kỹ thuật (`#0059CC` / ACI 5) | Hiển thị (`Visibility = True`) |
| **`04_Chu_Ghi_Chu`** | Chữ trong khung tên, bảng thông số, ghi chú kỹ thuật và yêu cầu gia công. | Xanh lục đậm (`#126138` / ACI 3) | Hiển thị (`Visibility = True`) |
| **`05_Model_3D`** | Mô hình mặt 3D (`SHELL_BASED_SURFACE_MODEL`) & khung dây 3D nhúng trong bản vẽ. | Màu vật liệu gốc từ SolidWorks | **Tự động ẩn (`Visibility = False`)** để không che khuất bản vẽ 2D (bấm `Space` để bật) |

> **Lưu ý với bản vẽ nhiều tờ:** Nếu file `.SLDDRW` có từ 2 tờ trở lên (`Sheet1`, `Sheet2`,...), mỗi tờ sẽ tự động có tiền tố tên tờ ở đầu từng Layer (ví dụ: `Sheet1_01_Khung_Ban_Ve`, `Sheet2_01_Khung_Ban_Ve`) và mỗi tờ được tạo một trang `TechDraw::DrawPage` riêng biệt (`Ban_Ve_2D_Sheet1`, `Ban_Ve_2D_Sheet2`).

## 3. Hướng dẫn cài đặt (Installation)

### Yêu cầu hệ thống

* **Bản vẽ 2D (`.SLDDRW`)**: Chỉ cần **Python 3.10+** chuẩn (sử dụng thư viện chuẩn của Python, không cần cài thêm bất kỳ gói phụ thuộc nào, chạy được trên Windows, Linux và macOS).
* **Chi tiết & Lắp ghép 3D (`.SLDPRT`, `.SLDASM`)**:
  * **Chế độ Open-Source (không cần SolidWorks)**: Cần **Python 3.10 – 3.14 (64-bit)** và **Git**. Lệnh `--setup` sẽ tự động tạo môi trường ảo (`~/.sw2step/venv`) và cài đặt [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step), [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step), `sldprt2xt`, cùng [CadQuery/OCP](https://github.com/cadquery/OCP).
  * **Chế độ SolidWorks COM (tuỳ chọn trên Windows có cài SolidWorks)**: Cần `pip install pywin32`.

### Cách 1: Cài đặt 1 chạm ngay từ trong giao diện FreeCAD (Khuyên dùng)

1. Mở [FreeCAD](https://www.freecad.org/downloads.php), trên thanh menu chọn **Macro** $\rightarrow$ **Macros...**
2. Bấm nút **...** ở mục *User macros location* (hoặc chép `sw2step.py` vào thư mục Macro), chọn file **`sw2step.py`** rồi bấm **Execute**.
3. Script sẽ tự động:
   * Cài đặt plugin `SolidWorksImporter` (`Init.py`, `importSLD.py`, `sw2step.py`) vào thư mục `Mod` của FreeCAD.
   * Kích hoạt ngay bộ đọc `.SLDPRT`, `.SLDASM`, `.SLDDRW` trong phiên làm việc hiện tại **mà không cần khởi động lại FreeCAD**.
   * Mở hộp thoại để bạn chọn file SolidWorks và xem ngay lập tức.

### Cách 2: Cài đặt từ Terminal / Command Prompt

```bash
# Cài đặt đầy đủ backend opensource (cho .SLDPRT/.SLDASM) và cài plugin vào FreeCAD
python sw2step.py --setup --install-freecad

# Nếu chỉ cần cài nhanh plugin FreeCAD (mở ngay được .SLDDRW bằng thuần Python)
python sw2step.py --install-freecad
```

Sau khi cài đặt, bạn có thể mở file SolidWorks trong FreeCAD theo 3 cách tự nhiên:
* Bấm **`Ctrl + O`** (`File` $\rightarrow$ `Open`) hoặc `File` $\rightarrow$ `Import` trong FreeCAD và chọn trực tiếp file `.SLDPRT`, `.SLDASM`, `.SLDDRW`.
* **Kéo-thả (Drag & Drop)** file từ thư mục máy tính vào thẳng cửa sổ FreeCAD.
* Click chuột phải vào file trong Windows Explorer $\rightarrow$ **Open with** $\rightarrow$ **FreeCAD**.

## 4. Hướng dẫn sử dụng dòng lệnh (CLI Usage)

### Các lệnh thông dụng

```bash
# 1. Chuyển đổi bản vẽ .SLDDRW sang STEP (mặc định) và mở ngay trong FreeCAD
python sw2step.py 2.SLDDRW --open

# 2. Xuất bản vẽ .SLDDRW sang AutoCAD DXF (chia sẵn 4 Layer màu ACI) hoặc SVG tỷ lệ 1:1
python sw2step.py 2.SLDDRW --ext dxf
python sw2step.py 2.SLDDRW --ext svg

# 3. Chỉ xuất riêng tờ số 1 của bản vẽ nhiều tờ
python sw2step.py BanVeNhieuTo.SLDDRW --ext dxf --sheet 1

# 4. Chẩn đoán cấu trúc bên trong file .SLDDRW (liệt kê các luồng, số tờ, khổ giấy, số nét mỗi Layer)
python sw2step.py 2.SLDDRW --inspect

# 5. Chuyển đổi file Part (.SLDPRT) hoặc Assembly (.SLDASM) và mở trong FreeCAD
python sw2step.py detail.SLDPRT --open
python sw2step.py assembly.SLDASM --fasteners --open

# 6. Chuyển đổi hàng loạt cả thư mục (quét đệ quy, chạy 4 luồng song song, xuất báo cáo CSV)
python sw2step.py "D:\Project_CAD" -r -o "D:\STEP_Out" --jobs 4 --report report.csv
```

### Bảng tra cứu đầy đủ tham số CLI

| Tham số | Mô tả chi tiết |
| :--- | :--- |
| `input` | Một hoặc nhiều đường dẫn file, thư mục hoặc mẫu wildcard (`*.sldprt`, `*.slddrw`). |
| `-o`, `--output <DIR>` | Thư mục chứa file kết quả (mặc định: lưu cùng thư mục với file gốc). |
| `-r`, `--recursive` | Quét đệ quy toàn bộ các thư mục con. |
| `--ext {step,stp,dxf,svg}` | Định dạng đầu ra (mặc định: `step`; riêng `.slddrw` hỗ trợ thêm `dxf` và `svg`). |
| `--sheet <N>` | Chỉ trích xuất tờ bản vẽ số `N` (1, 2, ...) đối với file `.slddrw` có nhiều tờ. |
| `--open` | Tự động khởi chạy FreeCAD và mở ngay các file vừa chuyển đổi xong. |
| `--inspect` | Phân tích và in chi tiết cấu trúc container `.slddrw` (danh sách luồng, số tờ, màu RGB, thống kê từng Layer). |
| `--backend {auto,solidworks,opensource}` | Chọn công cụ chuyển đổi (`auto`: ưu tiên SolidWorks COM nếu có trên máy, sau đó tới `opensource`). |
| `--setup` | Tự động tải và cài đặt bộ công cụ mã nguồn mở vào `~/.sw2step` (hoặc `%USERPROFILE%\.sw2step`). |
| `--install-freecad` | Cài đặt hoặc cập nhật plugin `SolidWorksImporter` vào thư mục `Mod` của FreeCAD. |
| `--fast` | Ưu tiên tốc độ cho `.sldprt`: dùng ngay kết quả của `sld2step` nếu đã sinh được khối B-rep. |
| `--no-fallback` | Không gọi `sldprt2step` dự phòng khi `sld2step` báo cảnh báo. |
| `--fasteners` | Tự động dựng hình học 3D cho ốc vít tiêu chuẩn (SHCS/BHCS) khi chuyển đổi `.sldasm`. |
| `--asm-root <DIR>` | Chỉ định thêm thư mục tìm kiếm các chi tiết `.sldprt` con cho file lắp ghép `.sldasm` (có thể lặp lại). |
| `-j`, `--jobs <N>` | Số tiến trình chuyển đổi chạy song song (áp dụng cho backend `opensource`). |
| `--overwrite` | Ghi đè file đích kể cả khi file đích đã tồn tại và mới hơn file gốc. |
| `--no-cache` | Bỏ qua bộ nhớ đệm, bắt buộc giải mã và chuyển đổi lại từ đầu. |
| `--clear-cache` | Xoá sạch toàn bộ bộ nhớ đệm STEP trong `~/.sw2step/cache`. |
| `--report <FILE.csv>` | Xuất bảng thống kê kết quả chuyển đổi (thời gian, trạng thái, ghi chú) ra file CSV (UTF-8 BOM). |

### Biến môi trường hỗ trợ

* `SW2STEP_HOME`: Thay đổi thư mục lưu trữ công cụ và cache (mặc định: `~/.sw2step`).
* `SW2STEP_SAVE_ALONGSIDE=1`: Khi mở file trực tiếp trong FreeCAD, lưu luôn file `.step` nằm cạnh file `.SLDPRT` / `.SLDASM` / `.SLDDRW` gốc thay vì chỉ lưu trong thư mục cache.
* `FREECAD_BIN`: Chỉ định đường dẫn tới file thực thi `FreeCAD.exe` / `freecad` nếu cài ở thư mục tuỳ chỉnh.

## 5. Lời cảm ơn & Tri ân (Acknowledgments & Credits)

Dự án này được xây dựng dựa trên sự kết hợp giữa bộ giải mã nhị phân `.SLDDRW` / `GContainer` thuần Python và các công cụ mã nguồn mở tuyệt vời của cộng đồng CAD/CAE. Xin gửi lời cảm ơn chân thành nhất tới các tác giả và dự án sau:

* [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step) của tác giả **dsandall**: Nền tảng cốt lõi giúp chuyển đổi `.SLDPRT` và `.SLDASM` sang định dạng STEP thông qua việc trích xuất luồng Parasolid XT, xử lý biến đổi toạ độ lắp ghép (Assembly transforms), tái tạo ốc vít (`--fasteners`) và bản vá tương thích cho `sldprt2xt`.
* [**BlinkingSun/sldprt2step**](https://github.com/BlinkingSun/sldprt2step) của tác giả [**BlinkingSun**](https://github.com/BlinkingSun): Công cụ chuyển đổi `.SLDPRT` sang chuẩn ISO 10303-21 STEP đóng vai trò làm nhánh dự phòng (fallback) và đối chiếu độ chính xác hình học B-rep cực kỳ hiệu quả.
* **`sldprt2xt`**: Thư viện phân tích cấu trúc container SolidWorks và trích xuất dữ liệu hình học Parasolid XT.
* [**CadQuery / OCP**](https://github.com/cadquery/OCP) và [**CadQuery/ocp-build-system**](https://github.com/CadQuery/ocp-build-system): Bộ thư viện Python bọc nhân hình học OpenCASCADE Technology (OCCT), cung cấp các công cụ kiểm tra tính hợp lệ của khối rắn (`BRepCheck_Analyzer`), tính toán thể tích (`BRepGProp`) và đọc/ghi chuẩn STEP.
* [**FreeCAD**](https://github.com/freecad/freecad): Phần mềm CAD 3D tham số mã nguồn mở mạnh mẽ với kiến trúc mở rộng linh hoạt (`FreeCAD.addImportType`, `ImportGui`, và workbench `TechDraw`), giúp hiện thực hoá trải nghiệm mở trực tiếp file SolidWorks chỉ với thao tác `Ctrl+O` hoặc kéo-thả.

## 6. Tài liệu kỹ thuật & Đóng góp (Technical Docs & Contributing)

* Để tìm hiểu chi tiết về cấu trúc nhị phân của file SolidWorks 2015+ (`GContainer`, cách giải mã `Contents/DisplayLists`, `Contents/VBLists`, thuật toán tách Sheet, tách Layer theo toạ độ $Z$, và tiêm màu STEP AP214), vui lòng xem file tài liệu kỹ thuật đi kèm: **`DOCS_TECHNICAL.md`**.
* Mọi đóng góp (Pull Requests), báo lỗi (Issues) hoặc mẫu file kiểm thử (đặc biệt là các bản vẽ `.SLDDRW` nhiều tờ hoặc `.SLDPRT` nhiều body phức tạp) đều được chào đón!

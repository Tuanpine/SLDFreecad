# Tài liệu Kỹ thuật & Giải mã Định dạng SolidWorks (`DOCS_TECHNICAL.md`)

Tài liệu này mô tả chi tiết kiến trúc bên trong của `sw2step.py` (phiên bản `2026.10.22-v3`), bao gồm cách kết hợp các backend mã nguồn mở cho `.SLDPRT` / `.SLDASM` và đặc tả kỹ thuật dịch ngược (reverse-engineering notes) định dạng container nhị phân `GContainer` của SolidWorks 2015+ đối với bản vẽ kỹ thuật `.SLDDRW`.

## 1. Kiến trúc tổng thể (Architecture Overview)

`sw2step.py` hoạt động theo mô hình đường ống lai (Hybrid Pipeline) gồm 3 nhánh xử lý chính:

| Thành phần | Định dạng đảm nhận | Cơ chế hoạt động |
| :--- | :--- | :--- |
| **`OpenSourceBackend`** | `.SLDPRT`, `.SLDASM` | Gọi [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step) để trích xuất luồng Parasolid XT và dựng khối B-rep qua [CadQuery/OCP](https://github.com/cadquery/OCP); nếu khối B-rep có cảnh báo, tự động chạy [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step) và dùng `BRepCheck_Analyzer` chọn kết quả hợp lệ nhất, sau đó hậu xử lý gắn màu STEP AP214 (`inject_step_ap214_colors`). |
| **`BuiltinDrwBackend`** | `.SLDDRW` | Giải mã hoàn toàn bằng **thuần Python** (`unpack_sld_gcontainer` $\rightarrow$ `parse_slddrw_geometry` $\rightarrow$ `write_slddrw_step` / `write_slddrw_dxf` / `write_slddrw_svg`), không phụ thuộc vào môi trường ảo hay thư viện bên ngoài. |
| **`SolidWorksBackend`** | `.SLDPRT`, `.SLDASM`, `.SLDDRW` | Điều khiển SolidWorks qua giao diện COM (`SldWorks.Application` trên Windows nếu có cài bản quyền SolidWorks); riêng khi xuất `.SLDDRW` sang `.STEP` vẫn định tuyến về `BuiltinDrwBackend` vì lệnh `SaveAs3` mặc định của SolidWorks không xuất bản vẽ 2D sang STEP. |

## 2. Giải mã Container `GContainer` (SolidWorks 2015+)

Từ phiên bản SolidWorks 2015 trở đi, các tệp `.SLDPRT`, `.SLDASM` và `.SLDDRW` không còn dùng định dạng Microsoft Compound File Binary (OLE2 `D0 CF 11 E0...`) mà chuyển sang định dạng nén nối tiếp gọi là **`GContainer`**.

### 2.1. Điểm neo khối dữ liệu (`_BLOCK_MARKER`)

* 4 byte đầu tiên của file **không phải** là magic bytes cố định (mỗi file có một giá trị khác nhau, ví dụ `04 63 32 5b` hoặc `1e 4d 27 95`), và độ dài phần mở đầu trước entry đầu tiên dao động từ 18 đến 20 byte.
* Do đó, `unpack_sld_gcontainer()` không nhảy theo kích thước cố định từ đầu file mà quét tìm mẫu 6 byte cố định `_BLOCK_MARKER = b"\x14\x00\x06\x00\x08\x00"` (tương ứng với `ver1 = 6`, `ver2 = 8` ở offset `+2` của mỗi entry header).

### 2.2. Cấu trúc Header 28 byte của mỗi luồng (Stream Entry)

Mỗi entry bắt đầu tại vị trí `marker_offset - 2` với cấu trúc `<IHHIIIII` (28 byte, little-endian):

| Offset | Kiểu dữ liệu | Tên trường | Ý nghĩa |
| :--- | :--- | :--- | :--- |
| `+0` | `uint32` | `u0` | Cờ / ID khối (2 byte cao luôn là `0x0014`) |
| `+4` | `uint16` | `ver1` | Luôn bằng `6` (`0x0006`) |
| `+6` | `uint16` | `ver2` | Luôn bằng `8` (`0x0008`) |
| `+8` | `uint32` | `ts` | Dấu thời gian (Timestamp) |
| `+12` | `uint32` | `crc` | Mã kiểm tra `CRC32` của luồng sau khi giải nén |
| `+16` | `uint32` | `csize` | Kích thước dữ liệu nén (`compressed_size`) |
| `+20` | `uint32` | `usize` | Kích thước dữ liệu gốc sau khi giải nén (`uncompressed_size`) |
| `+24` | `uint32` | `name_len` | Độ dài tên luồng (tính bằng byte) |
| `+28` | `bytes[name_len]` | `raw_name` | Tên luồng đã bị đảo bán byte (nibble-swapped) |

* **Giải mã tên luồng (`_swap_nibbles`)**: Mỗi byte `x` trong `raw_name` bị hoán vị 4 bit cao và 4 bit thấp: `((x >> 4) | ((x & 0x0F) << 4))`. Sau khi hoán vị và giải mã UTF-8, ta thu được đường dẫn luồng chuẩn như `Contents/DisplayLists`, `Contents/VBLists`, `SheetPreviews/SheetNames`, `ImportedComp/...`.
* **Giải nén dữ liệu**: Phần thân nén dài `csize` byte ngay sau tên luồng được nén bằng thuật toán **Raw Deflate** (không có header zlib), giải nén bằng `zlib.decompress(chunk, -15)` và đối chiếu `len(dec) == usize` cùng `zlib.crc32(dec) == crc`.

## 3. Giải mã Bản vẽ 2D & Mô hình 3D trong `.SLDDRW`

Một tệp `.SLDDRW` lưu trữ dữ liệu hiển thị của bản vẽ trong 3 luồng chính:
1. **`SheetPreviews/SheetNames`** và **`Images/Sheet_*`**: Danh sách tên các tờ bản vẽ (`Sheet1`, `Sheet2`,...).
2. **`Contents/DisplayLists`**: Chứa toàn bộ khung bản vẽ, khung tên, đường kích thước, mũi tên, văn bản ghi chú và các ma trận chiếu `Drawing View`.
3. **`Contents/VBLists`**: Chứa các bộ đường cong cạnh 3D (`uiViewBucket_c`), lưới mặt tam giác 3D (`uoTempFaceTessData_c`), và thông tin màu sắc vật liệu (`uoBodyPropInfo_c`, `moVisualProperties_c`).

### 3.1. Các Opcode hình học 2D trong `Contents/DisplayLists`

Mọi bản ghi đồ hoạ trong `DisplayLists` bắt đầu bằng cặp `<II` gồm `(record_size, opcode)` với toạ độ lưu bằng đơn vị **mét (`double`, 8 byte)**:

| `record_size` | `opcode` | Cấu trúc Payload | Ý nghĩa hình học |
| :--- | :--- | :--- | :--- |
| `0x50` (80B) | `0x04` | `<6d` tại offset `+8`: $(x_1, y_1, z_1, x_2, y_2, z_2)$ | Đoạn thẳng 2D (đường khung giấy, bảng biểu, đường gióng hoặc đường kích thước). |
| `0x78` (120B) | `0x06` | `<II` tại `+8` (`u1`, `npts=3`) + `<9d` tại `+16`: 3 đỉnh $(x, y, z)$ | Tam giác đặc đầu mũi tên kích thước (Dimension Arrowhead). |
| `0x80` (128B) | `0x02` | `<9d` tại `+8`: điểm đầu $(x_1, y_1, z_1)$, điểm cuối $(x_2, y_2, z_2)$, tâm $(x_c, y_c, z_c)$ | Đường tròn kín (nếu điểm đầu trùng điểm cuối trong khoảng `0.05mm`) hoặc cung tròn (`ARC`). |
| `0x6C` (108B) | `0x0A` | `<dI` tại `+8`: `(height_m: double, point_size: uint32)` | Bản ghi khai báo cỡ chữ (Font Header) đứng trước một hoặc nhiều bản ghi văn bản. |
| `0x50..0x1000` | `0x12` | `<5d` tại `pos - 40`: $(x, y, z, d_x, d_y)$ kèm chuỗi UTF-16LE sau dấu `\xff\xfe\xff` | Chuỗi văn bản 2D (nếu $|d_x| > 10^{10}$ thì chữ xoay dọc $90^\circ$). |

### 3.2. Quy tắc phân tách Layer: Khung bản vẽ ($Z = 0$) vs. Kích thước ($Z \neq 0$)

Khi khảo sát thực nghiệm luồng `Contents/DisplayLists`, chúng tôi phát hiện SolidWorks lưu trữ các đối tượng thuộc tờ giấy và các đối tượng thuộc chú thích kích thước ở hai mặt phẳng $Z$ khác nhau:
* **Đối tượng thuộc Khung bản vẽ & Khung tên (`01_Khung_Ban_Ve`, `04_Chu_Ghi_Chu`)**: Có toạ độ $|z| \le 10^{-6}\text{ m}$ ($z = 0.0$).
* **Đối tượng thuộc Kích thước gắn với Hình chiếu (`03_Kich_Thuoc`)**: Có toạ độ $|z| > 10^{-6}\text{ m}$ (ví dụ $z = -0.134931\text{ m}$ theo độ sâu của mặt phẳng hình chiếu).

Nhờ đặc tính này, `sw2step.py` tách chính xác 100% đường khung tên (`01_Khung_Ban_Ve`) khỏi đường gióng/đường kích thước (`03_Kich_Thuoc`), và tách chữ khung tên (`04_Chu_Ghi_Chu`) khỏi chữ số đo kích thước (`03_Kich_Thuoc`).

### 3.3. Thuật toán tách tờ cho Bản vẽ nhiều tờ (Multi-Sheet Splitting)

Trong `Contents/DisplayLists`, dữ liệu của mỗi tờ `Sheet_k` được ghi tuần tự theo cấu trúc:
1. Các đường thẳng khung giấy và chữ khung tên của `Sheet_k` (tại $z = 0$).
2. Các khối `Drawing View` (`view_hdr`) và kích thước của `Sheet_k` (tại $z \neq 0$).

Khi `SheetPreviews/SheetNames` khai báo số tờ $N > 1$, bộ phân tích sẽ theo dõi vị trí các `Drawing View`: ngay khi đã đi qua các `Drawing View` của tờ hiện tại mà gặp lại một chuỗi liên tiếp $\ge 8$ đoạn thẳng khung bản vẽ ở $z = 0$, vị trí đó được đánh dấu là điểm bắt đầu của tờ tiếp theo (`sheet_split_offsets`). Tờ thứ $k$ sẽ được cộng thêm độ dịch ngang `offset_x_mm = k * (sheet_width_mm + 50.0)` để các tờ xếp cạnh nhau từ trái sang phải.

### 3.4. Ma trận chiếu `Drawing View` & Khớp `uiViewBucket_c` theo pháp tuyến 3D

Mỗi hình chiếu 2D trên bản vẽ được định nghĩa bởi một header 44 byte (`3c 00 00 00 09 00 ...`), theo sau là:
* Cờ ma trận xoay `flag` (1 byte): nếu `flag == 0` thì ma trận xoay $R = I_3$ (hình chiếu đứng mặc định); nếu `flag != 0` thì 72 byte tiếp theo là 9 số `double` `<9d` biểu diễn ma trận trực giao $3 \times 3$ lưu theo thứ tự cột (**column-major**):
  $$x_{\text{sheet}} = c_x + o_x + s \cdot (r_0 x + r_3 y + r_6 z)$$
  $$y_{\text{sheet}} = c_y + o_y + s \cdot (r_1 x + r_4 y + r_7 z)$$
  trong đó $s$ là tỷ lệ hình chiếu (`scale`), $(o_x, o_y, o_z)$ là độ lệch tâm mô hình, và $(c_x, c_y, c_z)$ là tâm hình chiếu trên tờ giấy (đơn vị mét).
* Cột thứ 3 của ma trận xoay $\vec{v}_z = (r_2, r_5, r_8)$ chính là **vector pháp tuyến hướng nhìn 3D** của hình chiếu đó. `sw2step.py` đọc vector pháp tuyến 3D lưu ở đầu mỗi `uiViewBucket_c` trong `Contents/VBLists` và tìm bucket có $|\vec{v}_z \cdot \vec{n}_{\text{bucket}}| > 0.95$, giúp mỗi hình chiếu luôn nhận đúng tập cạnh khuất/cạnh thấy 3D của góc nhìn đó.

## 4. Trích xuất Màu sắc & Tiêm chuẩn STEP AP214 (`STYLED_ITEM`)

### 4.1. Vị trí lưu màu trong Container SolidWorks

`extract_sld_colors()` quét hai cấu trúc nhị phân trong `Contents/VBLists` và `Contents/DisplayLists`:
1. **`uoBodyPropInfo_c`**: Chứa thông tin vật liệu của từng Body (ví dụ `SolidWorks Materials|5052-H34`). Ngay sau chuỗi đánh dấu `\x0e\x80\x00\x00\x00\x00` + 16 byte `0xFF` là 4 byte `R G B 00`.
2. **`moVisualProperties_c`**: Tại offset `+36` tính từ cuối tên lớp `moVisualProperties_c` là 4 byte `R G B 00` biểu diễn màu sắc hiển thị tổng thể của chi tiết.

### 4.2. Cấu trúc thực thể màu STEP AP214

Để [FreeCAD](https://github.com/freecad/freecad) (`ImportGui`) và các phần mềm CAD khác nhận diện được màu của cả khối rắn/mặt 3D lẫn các Layer đường nét 2D, `sw2step.py` sinh chuỗi thực thể chuẩn **ISO 10303-214 (`AUTOMOTIVE_DESIGN`)**:

* **Đối với đường nét 2D (`GEOMETRIC_CURVE_SET`)**:
  ```step
  #10 = DRAUGHTING_PRE_DEFINED_CURVE_FONT('continuous');
  #11 = COLOUR_RGB('', 0.0000, 0.3500, 0.8000);
  #12 = CURVE_STYLE('', #10, POSITIVE_LENGTH_MEASURE(0.18), #11);
  #13 = PRESENTATION_STYLE_ASSIGNMENT((#12));
  #14 = STYLED_ITEM('', (#13), #CurveSetID);
  ```
* **Đối với khối rắn / mặt 3D (`MANIFOLD_SOLID_BREP` / `SHELL_BASED_SURFACE_MODEL`)**:
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
* Tất cả các `#STYLED_ITEM` được gom vào thực thể gốc `MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('', (#14, #27, ...), #GeomContextID)`.

## 5. Tài liệu tham khảo (References)

* [dsandall/sld2step](https://www.google.com/search?q=https://github.com/dsandall/sld2step) — Chuyển đổi `.SLDPRT` / `.SLDASM` sang STEP qua Parasolid XT và OpenCASCADE.
* [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step) — Chuyển đổi `.SLDPRT` sang ISO 10303-21 STEP.
* [CadQuery/OCP](https://github.com/cadquery/OCP) — Python bindings cho OpenCASCADE Technology (OCCT).
* [FreeCAD Source & Documentation](https://github.com/freecad/freecad) — Kiến trúc plugin `FreeCAD.addImportType`, `ImportGui` và `TechDraw`.

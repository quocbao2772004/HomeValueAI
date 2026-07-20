# Báo Cáo: Chiến Lược Lựa Chọn Dữ Liệu Cho Giai Đoạn Build Phase (MVP)

**Dự án:** Đề tài 132 - AI Định Giá & Tư Vấn Giá Thuê/Bán Lại Căn Hộ Trong Đại Đô Thị
**Giai đoạn:** Build Phase (MVP - Minimum Viable Product)

---

## 1. Đặt Vấn Đề
Mục tiêu của giai đoạn MVP là xây dựng một hệ thống hoàn chỉnh từ Frontend đến Backend, có tích hợp Machine Learning và LLM để chứng minh tính khả thi của dự án.
Vấn đề cốt lõi của Machine Learning là **"Garbage In, Garbage Out"**. Nếu chọn dữ liệu dàn trải toàn bộ thị trường Việt Nam hay toàn Hà Nội, mô hình MVP sẽ thất bại do lượng dữ liệu nhỏ không đủ để học các biến động phức tạp của toàn thị trường.

Do đó, báo cáo này đề xuất chiến lược lựa chọn dữ liệu tập trung (Laser-focused) để tối ưu hóa độ chính xác của AI trong thời gian ngắn nhất.

## 2. Đề Xuất Lựa Chọn Dữ Liệu Cho MVP

**Quyết định:** Chỉ lựa chọn tập dữ liệu (Dataset) các căn hộ mua bán/cho thuê thuộc **MỘT Đại Đô Thị Duy Nhất**.

**Đề xuất cụ thể:** Chọn khu đô thị **Vinhomes Ocean Park 1 (Gia Lâm, Hà Nội)** làm "phòng thí nghiệm" cho MVP.

### Tại sao lại chọn Vinhomes Ocean Park 1?
1. **Lượng giao dịch thứ cấp khổng lồ:** Đây là đại đô thị có số lượng căn hộ cực lớn (hàng chục tòa nhà), do đó dữ liệu rao bán/cho thuê trên các nền tảng (Batdongsan, Nhatot) hoặc nhóm Facebook rất dồi dào, dễ dàng thu thập đủ 500 - 1000 mẫu trong thời gian ngắn.
2. **Tính đồng nhất cao:** Các tiện ích cơ bản (phí dịch vụ, công viên, trường học, bệnh viện) là giống nhau cho toàn bộ cư dân. Điều này giúp loại bỏ các "nhiễu" do vị trí vĩ mô mang lại, giúp mô hình ML tập trung học các yếu tố vi mô của từng căn.
3. **Các trọng số định giá cực kỳ rõ nét:** Tại Ocean Park, giá căn hộ bị ảnh hưởng rất mạnh và quy chuẩn bởi các yếu tố:
   - Phân khu: (Sapphire luôn rẻ hơn Zenpark, Ruby).
   - Tầm View: (View nội khu rẻ hơn View hồ Ngọc Trai hay Biển hồ nước mặn).

## 3. Các Biến Số (Features) Trọng Tâm Cần Thu Thập
Thay vì thu thập quá nhiều trường thông tin rác, MVP Data Pipeline chỉ cần thiết kế để bóc tách 7 biến số cốt lõi:

| Feature Name | Kiểu Dữ Liệu | Vai Trò | Ví Dụ |
| :--- | :--- | :--- | :--- |
| `dien_tich` | Float (m2) | Biến đầu vào (X) quan trọng nhất | `54.5`, `80.0` |
| `so_phong_ngu` | Integer | Phân loại loại hình căn hộ | `1`, `2`, `3` |
| `phan_khu` | Categorical | Phân tầng giá trị tòa nhà | `Sapphire`, `Zenpark` |
| `khoang_tang` | Categorical | Ảnh hưởng đến thói quen mua | `Thấp`, `Trung`, `Cao` |
| `tam_view` | Categorical | Yếu tố cộng thêm giá | `Nội khu`, `Hồ`, `Thành phố` |
| `noi_that` | Categorical | Yếu tố trừ khấu hao | `Trống`, `Cơ bản`, `Full đồ` |
| `gia_tien` | Float (Tỷ/Triệu) | **Biến mục tiêu (Y)** cần dự đoán | `2.15`, `3.5` |

## 4. Kế Hoạch Triển Khai Xử Lý Data (Data Pipeline Strategy)

Để đảm bảo tiến độ Build Phase, quy trình xử lý Data sẽ chia làm 2 bước chạy song song:

- **Bước 1: Build Pipeline với Dummy Data (Tuần 1)**
  - Tận dụng ngay file `backend/data/real_estate_raw.csv` (60 dòng dữ liệu ngẫu nhiên) làm tập "Dummy Data".
  - Code toàn bộ các class làm sạch dữ liệu (`DataCleaner`), mã hóa biến Categorical (`LabelEncoder`), và xây dựng luồng huấn luyện XGBoost. Mục đích để kết nối thông suốt từ file `.csv` ra thành API dự đoán.
  - *Kết quả:* Hệ thống chạy được nhưng kết quả định giá chưa chính xác.

- **Bước 2: Thay thế Real Data (Tuần 2)**
  - Viết Crawler chuyên biệt tập trung vào từ khóa "Căn hộ Vinhomes Ocean Park" để lấy về ~1000 samples.
  - Thay thế file CSV cũ bằng tập dữ liệu Ocean Park.
  - Chạy lại lệnh Train Model. Do code Pipeline ở Bước 1 đã hoàn thiện, mô hình tự động học trên dữ liệu mới và đạt độ chính xác thực tế (có thể kỳ vọng R2 Score > 85%).
  - Tích hợp thêm Prompt cho LLM để giải thích các yếu tố định giá dựa trên thuộc tính của căn hộ (ví dụ: giải thích tại sao view Hồ lại đắt hơn).

## 5. Kết Luận
Việc khóa chặt phạm vi dữ liệu vào **1 Đại đô thị (Vinhomes Ocean Park)** với **7 biến số** là nước đi chiến lược quan trọng nhất cho giai đoạn MVP. Nó cân bằng giữa khả năng thu thập dữ liệu khả thi và độ chính xác bắt buộc phải có của một bài toán ML định giá, đồng thời thể hiện đúng tinh thần "Giải quyết nỗi đau của thị trường thứ cấp nội khu" như yêu cầu đề tài.

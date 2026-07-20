# Project Brief: AI Định Giá Bất Động Sản Đại Đô Thị

**Mã đề tài:** C2-Team-134 (AI20K-132)
**Tên dự án:** AI Định Giá & Tư Vấn Giá Thuê/Bán Lại Căn Hộ Trong Đại Đô Thị (Focus: Vinhomes Ocean Park 1)
**Lĩnh vực:** PropTech (Real Estate - Valuation)
**Công nghệ lõi:** Machine Learning (Random Forest) + LLM (OpenAI/Claude)

---

## 1. Bối Cảnh & Nỗi Đau (Pain Point)
Thị trường bất động sản thứ cấp (mua bán/cho thuê lại) trong các Đại đô thị (Mega-cities) như Vinhomes Ocean Park đang đối mặt với tình trạng "loạn giá".
- **Người bán/Cho thuê:** Không biết định giá căn hộ của mình bao nhiêu là hợp lý. Nếu rao quá cao thì "ngâm" hàng nửa năm không ai hỏi, nếu rao quá thấp thì bị hớ.
- **Môi giới:** Thường "bơm thổi" giá hoặc ép giá tùy thuộc vào lợi ích hoa hồng.
- **Người mua/Thuê:** Hoang mang giữa ma trận giá ảo (chênh lệch 10-20% so với giá giao dịch thực tế) trên các trang rao vặt.

*(Chi tiết các nỗi đau này đã được kiểm chứng thông qua phỏng vấn người dùng thực tế. Vui lòng xem thêm tại file `5_Real_User_Survey_Report.md`).*

Sự thiếu minh bạch này làm giảm tính thanh khoản của thị trường nội khu và gây mất niềm tin cho cả hai bên giao dịch.

## 2. Giải Pháp AI (The Solution)
Hệ thống **PropTech AI** chuyên biệt định giá cho các căn hộ nội khu. Hệ thống hoạt động theo 2 tầng:
1. **Machine Learning (Predictive AI):** Sử dụng các thuật toán như Random Forest Regression, học từ hàng ngàn dữ liệu giao dịch thực tế và tin rao chuẩn. Mô hình bóc tách chính xác giá trị của từng yếu tố cấu thành giá: Phân khu, số tầng, tầm view, diện tích, nội thất... để đưa ra **Một con số định giá thực**.
2. **Generative AI (Explainable AI - XAI):** Thay vì chỉ ném cho người dùng một con số khô khan (Black-box), hệ thống tích hợp LLM (ChatGPT/Claude) để tự động sinh ra một văn bản phân tích, giải thích mạch lạc bằng tiếng Việt tại sao căn hộ lại có mức giá đó.

## 3. Mục Tiêu Dự Án (Objectives)
- **Minh bạch hóa thị trường thứ cấp:** Tạo ra một "Barem giá" chuẩn tham chiếu chung cho cả người mua, người bán và môi giới (Giải quyết triệt để các Pain Points thu thập từ khảo sát người dùng).
- **Rút ngắn thời gian chốt sale:** Khi giá rao sát với giá thực tế, tỷ lệ chốt giao dịch sẽ diễn ra nhanh hơn gấp 2-3 lần.
- **Tạo USP (Unique Selling Proposition) khác biệt:** Trở thành nền tảng định giá duy nhất có khả năng "giải thích lý do" bằng văn phong chuyên gia.

## 4. Khách Hàng Mục Tiêu (Target Audience)
- **Chủ nhà (Sellers/Landlords):** Cần công cụ tham chiếu để set giá hợp lý trước khi gửi môi giới.
- **Người mua/Người thuê (Buyers/Tenants):** Cần công cụ kiểm tra xem mức giá môi giới báo có bị "ngáo giá" hay không.
- **Môi giới (Brokers):** Dùng báo cáo định giá AI của hệ thống làm công cụ thuyết phục khách hàng chốt cọc nhanh.

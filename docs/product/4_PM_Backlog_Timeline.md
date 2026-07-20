# Project Management: Timeline & Backlog

**Dự án:** AI Định Giá Căn Hộ Đại Đô Thị (HomeValue AI)

Tài liệu này được sử dụng để quản lý tiến độ, phân chia công việc (Sprint Backlog) và theo dõi trạng thái các hạng mục kỹ thuật của toàn dự án trong 6 tuần.

---

## 1. Timeline Dự Án & Các Cột Mốc (Milestones)
| Tuần / Sprint | Cột mốc & Hạn chót (Deadline) | Giai đoạn | Nội dung Triển Khai |
|---|---|---|---|
| **Tuần 1 (Sprint 1)** | **Gate G1 — Chốt đề tài**<br>*(23:50, 07/06/2026)* | Phase 1 | Hoàn thành Kick-off, Khảo sát Pain Points, Viết Brief, PRD, Phân tích đối thủ và Sơ đồ Wireframe. |
| **Tuần 2 (Sprint 2)** | **Gate G2 — Bản MVP**<br>*(23:59, 18/06/2026)* | Phase 1 | Build nền tảng Core Backend (Data Pipeline, ML Model, FastAPI, LLM). Chạy thành công MVP Agent. |
| **Tuần 3 (Sprint 3)** | Core Hoàn Thiện | Phase 1 | Lập trình Frontend Next.js, kết nối API backend, hoàn thiện UI/UX. |
| **Tuần 4 (Sprint 4)** | Optimize & Tuning | Phase 2 | Optimize + Build Hours: Tối ưu hóa LLM prompt, cải thiện R2 score của ML, test hiệu năng trên Mobile. |
| **Tuần 5 (Sprint 5)** | Deploy & Onboard | Phase 2 | Deploy & Onboard users: Đưa Frontend lên Vercel, Backend lên Render. Chạy thử nghiệm lấy Feedback. |
| **Tuần 6 (Sprint 6)** | **Demo Day 🏆**<br>*(09/07/2026)* | Phase 2 | Chuẩn bị Pitch Deck, thuyết trình và trình diễn hệ thống Live Demo trước hội đồng. |

## 2. Kanban Board (Sprint Backlog Tracking)

| ID | Task Name (Feature) | Assignee | Status | Sprint | Priority |
|---|---|---|---|---|---|
| T1 | Phân tích đối thủ & Chọn Dữ Liệu (VOP1) | Toàn Team | ✅ Done | Sprint 1 | High |
| T2 | Khảo sát Pain Points người dùng | Toàn Team | ✅ Done | Sprint 1 | High |
| T3 | Viết Brief, PRD, Wireframe & Timeline | Toàn Team | ✅ Done | Sprint 1 | High |
| T4 | Build Data Pipeline (`crawler_vop.py`) | Backend Dev | 🔄 In Progress | Sprint 2 | High |
| T5 | Train ML Model RandomForest (`train.py`) | AI Engineer | 🔄 In Progress | Sprint 2 | High |
| T6 | Xây dựng FastAPI & LLM Endpoint | Backend Dev | 🔄 In Progress | Sprint 2 | High |
| **M1** | **Đóng gói & Release phiên bản MVP (Gate G2)** | **Toàn Team** | ⏳ **To Do** | **Sprint 2** | **Critical**|
| T7 | Setup Next.js & Tailwind CSS Frontend | Frontend Dev | ⏳ To Do | Sprint 3 | High |
| T8 | Code Giao diện Form Định Giá & Kết quả | Frontend Dev | ⏳ To Do | Sprint 3 | High |
| T9 | Ghép nối API Backend vào Web App | Fullstack | ⏳ To Do | Sprint 3 | Critical|
| T10| Tuning Model & Optimize Prompts | AI Engineer | ⏳ To Do | Sprint 4 | Medium |
| T11| Deploy hệ thống lên Vercel/Render | DevOps | ⏳ To Do | Sprint 5 | High |
| T12| Chuẩn bị Pitch Deck & Video Demo Day | Toàn Team | ⏳ To Do | Sprint 6 | High |

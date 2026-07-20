/**
 * Cấu hình bot Zalo HomeValue AI.
 * Đọc từ biến môi trường, có giá trị mặc định hợp lý cho production.
 */
import path from "node:path";

const __dirname = path.dirname(new URL(import.meta.url).pathname);

export const config = {
  // Đường dẫn credentials Zalo
  credsPath: path.join(__dirname, "credentials.json"),

  // Backend API
  apiBase: process.env.API_BASE || "http://127.0.0.1:1108",
  chatPath: process.env.CHAT_PATH || "/zalo/chat",
  // Timeout cho mỗi request tới API (ms). Câu định giá có thể chậm vì gọi tiện ích.
  apiTimeoutMs: Number(process.env.API_TIMEOUT_MS || 45000),
  // Số lần thử lại khi API lỗi mạng/timeout
  apiRetries: Number(process.env.API_RETRIES || 1),

  // Context hội thoại hết hạn sau bao lâu không nhắn (ms)
  contextTtlMs: Number(process.env.CONTEXT_TTL_MS || 15 * 60 * 1000),

  // Chống spam: tối thiểu giữa 2 tin của cùng user (ms)
  minMessageIntervalMs: Number(process.env.MIN_MSG_INTERVAL_MS || 1200),
  // Giới hạn độ dài tin nhắn nhận vào
  maxInputLength: Number(process.env.MAX_INPUT_LENGTH || 1000),
  // Zalo dễ lỗi với tin quá dài; chia phản hồi thành nhiều đoạn ngắn.
  maxReplyChunkLength: Number(process.env.MAX_REPLY_CHUNK_LENGTH || 1400),

  // Bật/tắt phản hồi "đang xử lý" cho câu hỏi định giá
  sendTypingHint: (process.env.SEND_TYPING_HINT || "1") === "1",
  // Mặc định trả lời cả nhóm Zalo; đặt 0 nếu chỉ muốn chat riêng.
  respondInGroups: (process.env.RESPOND_IN_GROUPS || "1") === "1",
  // Log tin bị bỏ qua để debug listener/content.
  debugMessages: (process.env.DEBUG_MESSAGES || "0") === "1",
};

// Tin nhắn cố định
export const messages = {
  welcome:
    "Xin chào! Mình là trợ lý định giá BĐS Vinhomes Hà Nội.\n" +
    "Bạn có thể hỏi ví dụ:\n" +
    "• Định giá bán căn hộ Vinhomes Smart City 54m2 2PN full nội thất\n" +
    "• Giá thuê căn hộ Vinhomes Ocean Park 2PN\n" +
    "• Xu hướng giá Ocean Park căn hộ\n\n" +
    "Gõ /help để xem hướng dẫn, /reset để bắt đầu lại.",
  help:
    "Hướng dẫn dùng trợ lý định giá:\n" +
    "• Nhập thông tin căn: dự án, diện tích, số phòng ngủ, nội thất, mục đích bán/thuê.\n" +
    "• Ví dụ: \"Vinhomes Smart City 54m2 2PN full nội thất, bán\".\n" +
    "• Mình sẽ trả khoảng giá hợp lý (P10/P50/P90), độ tin cậy và yếu tố ảnh hưởng.\n\n" +
    "Lệnh:\n" +
    "• /help — xem hướng dẫn\n" +
    "• /reset — xóa thông tin phiên hiện tại",
  reset: "Đã xóa thông tin phiên. Bạn có thể bắt đầu một câu hỏi định giá mới.",
  busy: "Hệ thống đang xử lý nhiều yêu cầu, bạn chờ chút rồi thử lại nhé.",
  apiError: "Xin lỗi, hệ thống định giá đang gặp sự cố. Vui lòng thử lại sau ít phút.",
  timeout: "Câu hỏi cần xử lý hơi lâu nên chưa kịp phản hồi. Bạn thử gửi lại giúp mình nhé.",
  tooLong: "Tin nhắn hơi dài. Bạn rút gọn thông tin căn hộ giúp mình nhé.",
  rateLimited: "Bạn gửi hơi nhanh, chờ một chút rồi gửi lại nhé.",
  typingHint: "Mình đang tính toán khoảng giá, chờ một chút nhé...",
  emptyAnswer: "Mình chưa có đủ thông tin để trả lời. Bạn thử mô tả rõ hơn về căn hộ nhé.",
};

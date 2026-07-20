/**
 * HomeValue AI - Zalo Chatbot (production)
 *
 * Tính năng:
 * - Tích hợp API định giá /chat với timeout + retry
 * - Context hội thoại per-user có TTL
 * - Lệnh /help, /reset; lời chào lần đầu
 * - Chống spam (rate limit), giới hạn độ dài input
 * - Phản hồi "đang xử lý" cho câu định giá chậm
 * - Tự reconnect khi listener đóng
 *
 * Chạy: npx tsx bot.ts
 * Trỏ API production: API_BASE=https://apivinhomes.solanai.us npx tsx bot.ts
 */
import fs from "node:fs";
import { Zalo, ThreadType } from "zca-js";
import type { API, Credentials, Message } from "zca-js";

import { config, messages } from "./config.ts";
import { callChat, healthCheck } from "./api.ts";
import {
  getContext,
  setContext,
  resetContext,
  isRateLimited,
  isFirstContact,
  startSessionCleanup,
} from "./session.ts";

function loadCreds(): Credentials {
  if (!fs.existsSync(config.credsPath)) {
    console.error("Chưa có credentials.json. Chạy: npx tsx login.ts");
    process.exit(1);
  }
  const raw = JSON.parse(fs.readFileSync(config.credsPath, "utf-8"));
  if (!raw.cookie || !raw.imei || !raw.userAgent) {
    console.error("credentials.json không hợp lệ. Chạy lại: npx tsx login.ts");
    process.exit(1);
  }
  return raw as Credentials;
}

function formatAnswer(answer: string): string {
  return answer.replace(/^- /gm, "• ").replace(/\*\*/g, "").trim();
}

function splitReply(text: string): string[] {
  const limit = Math.max(500, config.maxReplyChunkLength);
  const normalized = text.trim();
  if (normalized.length <= limit) return normalized ? [normalized] : [];

  const chunks: string[] = [];
  let current = "";
  for (const block of normalized.split(/\n{2,}/)) {
    const candidate = current ? `${current}\n\n${block}` : block;
    if (candidate.length <= limit) {
      current = candidate;
      continue;
    }
    if (current) chunks.push(current);
    if (block.length <= limit) {
      current = block;
      continue;
    }
    for (let index = 0; index < block.length; index += limit) {
      chunks.push(block.slice(index, index + limit));
    }
    current = "";
  }
  if (current) chunks.push(current);
  return chunks;
}

function extractText(msg: Message): string {
  const content = msg.data.content;
  if (typeof content === "string") return content.trim();
  if (!content || typeof content !== "object") return "";

  const candidates = [
    "text",
    "msg",
    "message",
    "title",
    "description",
    "href",
  ];
  for (const key of candidates) {
    const value = (content as Record<string, unknown>)[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function sessionKey(msg: Message): string {
  const sender = typeof msg.data.uidFrom === "string" && msg.data.uidFrom !== "0" ? msg.data.uidFrom : msg.threadId;
  return msg.type === ThreadType.Group ? `group:${msg.threadId}:${sender}` : `user:${msg.threadId}`;
}

function shouldHandleMessage(msg: Message): boolean {
  if (msg.isSelf) return false;
  if (msg.type === ThreadType.Group) return config.respondInGroups;
  return msg.type === ThreadType.User;
}

function ts(): string {
  return new Date().toISOString().slice(11, 19);
}

/** Xử lý lệnh đặc biệt. Trả về reply nếu là lệnh, null nếu không. */
function handleCommand(text: string, userId: string): string | null {
  const cmd = text.toLowerCase().trim();
  if (cmd === "/help" || cmd === "help" || cmd === "huong dan") return messages.help;
  if (cmd === "/reset" || cmd === "reset") {
    resetContext(userId);
    return messages.reset;
  }
  if (cmd === "/start" || cmd === "start") return messages.welcome;
  return null;
}

async function buildReply(text: string, userId: string): Promise<string> {
  // Lệnh
  const cmdReply = handleCommand(text, userId);
  if (cmdReply) return cmdReply;

  // Input quá dài
  if (text.length > config.maxInputLength) return messages.tooLong;

  // Gọi API
  const ctx = getContext(userId);
  const resp = await callChat(text, ctx);

  if (resp.status === "timeout") return messages.timeout;
  if (resp.status === "error") return messages.apiError;

  const result = resp.result!;
  setContext(userId, result.context);
  const answer = formatAnswer(result.answer);
  return answer || messages.emptyAnswer;
}

async function sendReplyChunks(api: API, reply: string, threadId: string, type: ThreadType): Promise<void> {
  const chunks = splitReply(reply);
  if (!chunks.length) {
    await api.sendMessage(messages.emptyAnswer, threadId, type);
    return;
  }
  for (const chunk of chunks) {
    await api.sendMessage(chunk, threadId, type);
  }
}

/** Nhận diện câu định giá để gửi typing hint (vì backend chậm hơn). */
function looksLikeValuation(text: string): boolean {
  const t = text.toLowerCase();
  return /(định giá|dinh gia|bao nhiêu|giá bán|giá thuê|gia ban|gia thue|m2|m²|phòng ngủ|pn)/.test(t);
}

async function attachListeners(api: API): Promise<void> {
  const { listener } = api;

  listener.on("message", async (msg) => {
    try {
      if (!shouldHandleMessage(msg)) {
        if (config.debugMessages) {
          console.log(`[${ts()}] ignored message type=${msg.type} self=${msg.isSelf}`);
        }
        return;
      }
      const text = extractText(msg);
      if (!text) {
        if (config.debugMessages) {
          console.log(`[${ts()}] ignored non-text message type=${msg.type} content=${typeof msg.data.content}`);
        }
        return;
      }

      const userId = sessionKey(msg);

      // Chống spam
      if (isRateLimited(userId)) {
        console.log(`[${ts()}] ${userId} rate-limited`);
        return;
      }

      console.log(`[${ts()}] ${userId}: ${text.slice(0, 80)}`);

      // Chào lần đầu (chỉ khi không phải lệnh)
      if (isFirstContact(userId) && !text.startsWith("/")) {
        await api.sendMessage(messages.welcome, msg.threadId, msg.type).catch((e: unknown) => {
          console.error(`[${ts()}] welcome send error:`, e);
        });
      }

      // Typing hint cho câu định giá
      const isCmd = text.startsWith("/");
      if (config.sendTypingHint && !isCmd && looksLikeValuation(text)) {
        await api.sendMessage(messages.typingHint, msg.threadId, msg.type).catch((e: unknown) => {
          console.error(`[${ts()}] typing hint send error:`, e);
        });
      }

      const reply = await buildReply(text, userId);
      console.log(`[${ts()}]   → ${reply.slice(0, 80).replace(/\n/g, " ")}`);
      await sendReplyChunks(api, reply, msg.threadId, msg.type);
    } catch (e) {
      console.error(`[${ts()}] handler error:`, e);
    }
  });

  listener.onConnected(() => console.log(`[${ts()}] 🟢 Listener connected`));
  listener.onClosed(() => console.log(`[${ts()}] 🔴 Listener closed`));
  listener.onError((e: unknown) => console.error(`[${ts()}] listener error:`, e));

  listener.start();
}

async function main() {
  console.log(`HomeValue AI Zalo Bot | API: ${config.apiBase}`);

  // Cảnh báo nếu backend chưa sẵn sàng (không chặn, chỉ báo)
  const healthy = await healthCheck();
  if (!healthy) {
    console.warn(`[${ts()}] ⚠️  Backend ${config.apiBase} chưa phản hồi /health. Bot vẫn chạy, sẽ thử khi có tin nhắn.`);
  } else {
    console.log(`[${ts()}] ✅ Backend OK`);
  }

  const creds = loadCreds();
  const zalo = new Zalo();
  const api: API = await zalo.login(creds);
  console.log(`[${ts()}] ✅ Đăng nhập Zalo OK`);

  await attachListeners(api);
  startSessionCleanup();

  // Giữ process sống
  process.on("SIGINT", () => {
    console.log(`\n[${ts()}] Dừng bot.`);
    process.exit(0);
  });
}

main().catch((e) => {
  console.error("Fatal:", e);
  process.exit(1);
});

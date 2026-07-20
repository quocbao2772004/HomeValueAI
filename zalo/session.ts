/**
 * Quản lý context hội thoại per-user với TTL và rate limiting.
 */
import { config } from "./config.ts";

interface Session {
  context: Record<string, unknown> | null;
  lastMessageAt: number;
}

const sessions = new Map<string, Session>();

function getOrCreate(userId: string): Session {
  let s = sessions.get(userId);
  if (!s) {
    s = { context: null, lastMessageAt: 0 };
    sessions.set(userId, s);
  }
  return s;
}

/** Trả về true nếu user gửi quá nhanh (spam). */
export function isRateLimited(userId: string): boolean {
  const s = getOrCreate(userId);
  const now = Date.now();
  if (now - s.lastMessageAt < config.minMessageIntervalMs) return true;
  s.lastMessageAt = now;
  return false;
}

export function getContext(userId: string): Record<string, unknown> | null {
  const s = sessions.get(userId);
  if (!s) return null;
  // Hết hạn context nếu lâu không nhắn
  if (Date.now() - s.lastMessageAt > config.contextTtlMs) {
    s.context = null;
  }
  return s.context;
}

export function setContext(userId: string, context: Record<string, unknown> | null): void {
  const s = getOrCreate(userId);
  s.context = context;
}

export function resetContext(userId: string): void {
  const s = sessions.get(userId);
  if (s) s.context = null;
}

/** Đánh dấu user đã từng được chào (welcome 1 lần). */
const greeted = new Set<string>();
export function isFirstContact(userId: string): boolean {
  if (greeted.has(userId)) return false;
  getOrCreate(userId);
  greeted.add(userId);
  return true;
}

/** Dọn session cũ định kỳ để tránh phình bộ nhớ. */
export function startSessionCleanup(): NodeJS.Timeout {
  return setInterval(
    () => {
      const now = Date.now();
      for (const [userId, s] of sessions.entries()) {
        if (now - s.lastMessageAt > config.contextTtlMs * 4) {
          sessions.delete(userId);
          greeted.delete(userId);
        }
      }
    },
    10 * 60 * 1000,
  );
}

/**
 * Đăng nhập Zalo qua QR code.
 * Chạy: npx tsx login.ts
 */
import fs from "node:fs";
import path from "node:path";
import { Zalo } from "zca-js";
import type { Credentials } from "zca-js";

const __dirname = path.dirname(new URL(import.meta.url).pathname);
const CREDS_PATH = path.join(__dirname, "credentials.json");
const QR_PATH = path.join(__dirname, "qr.png");

const zalo = new Zalo();

// Kiểm tra credentials cũ
function loadCreds(): Credentials | null {
  if (!fs.existsSync(CREDS_PATH)) return null;
  const raw = JSON.parse(fs.readFileSync(CREDS_PATH, "utf-8"));
  if (raw.cookie && raw.imei && raw.userAgent) return raw as Credentials;
  return null;
}

const existing = loadCreds();

let api;
if (existing) {
  console.log("Đang login bằng credentials cũ...");
  api = await zalo.login(existing);
} else {
  console.log("Tạo QR code...");
  api = await zalo.loginQR({ qrPath: QR_PATH, userAgent: "" });
  console.log(`\n✅ Quét QR tại: ${QR_PATH}`);
  console.log("Mở file qr.png và quét bằng Zalo trên điện thoại.\n");

  // Lưu credentials
  const ctx = api.getContext();
  const creds: Credentials = {
    cookie: ctx.cookie.toJSON()?.cookies || [],
    imei: ctx.imei,
    userAgent: ctx.userAgent,
  };
  fs.writeFileSync(CREDS_PATH, JSON.stringify(creds, null, 2), "utf-8");
  console.log("✅ Credentials đã lưu:", CREDS_PATH);
}

const profile = await api.fetchAccountInfo();
console.log("✅ Đăng nhập thành công:", JSON.stringify(profile, null, 2));
process.exit(0);

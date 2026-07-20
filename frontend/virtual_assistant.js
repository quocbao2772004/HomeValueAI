/**
 * Trang trợ lý định giá - HomeValue AI.
 * Dùng chung localStorage session với dashboard, gọi cùng API /chat (style prose để tương thích API live).
 */
const PRODUCTION_API_BASE = "/api";
const LOCAL_API_BASE = "http://127.0.0.1:8000";
const LOCAL_API_BASE_BY_PORT = {
  2707: "/api",
};
const CHAT_SESSIONS_KEY = "homevalue_chat_sessions";
const AUTH_SESSION_KEY = "homevalue_auth_session";
const PLAN_AGENT_PRO_MONTHLY = "agent_pro_monthly";
const PLAN_CREDITS_100 = "credits_100";
const MAX_CHAT_HISTORY = 120;
const MAX_SESSIONS = 20;
const REQUEST_TIMEOUT_MS = 45000;
const IS_EMBEDDED = new URLSearchParams(window.location.search).get("embed") === "1";
const INITIAL_AUTH = loadAuthSession();

const state = {
  apiBase: initialApiBase(),
  auth: INITIAL_AUTH,
  sessions: [],
  activeSessionId: null,
  chatHistory: [],
  pendingChatContext: null,
  conversationContext: null,
  credits: initialCredits(INITIAL_AUTH?.user),
  isPremium: isAuthUserPro(INITIAL_AUTH?.user),
  activePaymentOrder: null,
  paymentPollTimer: null,
  paymentPollOrderCode: null,
  paymentCheckInFlight: false,
};

function updateCreditUI() {
  const el = $("vaCreditBalance");
  const topUpBtn = $("vaTopUpBtn");
  const proBtn = $("vaUpgradeProSidebarBtn");
  
  if (state.isPremium) {
    if (el) el.textContent = "Gói: Agent Pro";
    if (topUpBtn) topUpBtn.style.display = "none";
    if (proBtn) proBtn.style.display = "none";
  } else {
    if (el) el.textContent = `Ví: ${state.credits} Credits`;
    if (topUpBtn) topUpBtn.style.display = "inline-block";
    if (proBtn) proBtn.style.display = "flex";
  }
  updatePdfButtonState();
}

const $ = (id) => document.getElementById(id);

function initialApiBase() {
  const local = new Set(["127.0.0.1", "localhost", "0.0.0.0", ""]);
  return local.has(window.location.hostname)
    ? (LOCAL_API_BASE_BY_PORT[window.location.port] || LOCAL_API_BASE)
    : PRODUCTION_API_BASE;
}

document.addEventListener("DOMContentLoaded", () => {
  if (IS_EMBEDDED) document.body.classList.add("va-embedded");
  loadSessions();
  bindEvents();
  renderUserScope();
  renderSessionList();
  renderChatHistory();
  autoSizeTextarea();
  refreshIcons();
  applyPremiumFromAuth();
  updateCreditUI();
  boot();
});

function bindEvents() {
  $("vaChatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = $("vaChatMessage").value.trim();
    if (!text) return;

    $("vaChatMessage").value = "";
    autoSizeTextarea();
    appendMessage("user", text);
    await runChat(text);
  });

  $("vaChatMessage").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("vaChatForm").requestSubmit();
    }
  });
  $("vaChatMessage").addEventListener("input", autoSizeTextarea);

  $("vaNewSession").addEventListener("click", () => {
    createSession();
    $("vaChatMessage").focus();
  });
  $("vaClearSession").addEventListener("click", deleteActiveSession);

  $("vaMenuToggle").addEventListener("click", () => {
    $("vaSidebar").classList.toggle("is-open");
  });

  $("vaTopUpBtn")?.addEventListener("click", () => {
    openProModal();
  });
  $("vaUpgradeProSidebarBtn")?.addEventListener("click", () => {
    openProModal();
  });
  $("vaProModalClose")?.addEventListener("click", () => {
    closeProModal();
  });
  $("vaProModal")?.addEventListener("click", (e) => {
    if (e.target.classList.contains("va-modal-backdrop")) {
      closeProModal();
    }
  });

  $("vaTopUpCreditBtn")?.addEventListener("click", startCreditPayment);
  $("vaBuyProBtn")?.addEventListener("click", startProPayment);

  $("vaExportPdfBtn")?.addEventListener("click", async () => {
    try {
      await apiPost("/export/pdf/check", {});
    } catch {
      openProModal();
      return;
    }
    if (!state.isPremium) {
      state.isPremium = true;
      updateCreditUI();
    }
    {
      const dateEl = $("printDate");
      if (dateEl) {
        const now = new Date();
        dateEl.textContent = `${now.getDate()}/${now.getMonth() + 1}/${now.getFullYear()} ${now.getHours()}:${now.getMinutes().toString().padStart(2, '0')}`;
      }
      
      const avatarEl = $("printAvatar");
      const avatarWrapper = $("printAvatarWrapper");
      const badgeEl = $("printProBadge");
      const savedAvatar = localStorage.getItem("homevalue_avatar");
      if (avatarWrapper && avatarEl && savedAvatar) {
        avatarEl.src = savedAvatar;
        avatarWrapper.style.display = "block";
        if (state.isPremium) {
          avatarEl.style.boxShadow = "0 0 0 2px #fff, 0 0 0 4px #D4AF37";
          if (badgeEl) badgeEl.style.display = "flex";
        } else {
          avatarEl.style.boxShadow = "0 0 0 2px #005a4e";
          if (badgeEl) badgeEl.style.display = "none";
        }
      } else if (avatarWrapper) {
        avatarWrapper.style.display = "none";
      }
      
      window.print();
    }
  });

  window.addEventListener("message", (event) => {
    if (event.data?.type === "homevalue:focus-assistant") {
      $("vaChatMessage")?.focus();
    }
    if (event.data?.type === "homevalue:auth-changed") {
      reloadAuthScope();
      renderChatHistory();
    }
  });

  window.addEventListener("storage", (event) => {
    if (event.key === AUTH_SESSION_KEY) {
      reloadAuthScope();
    }
  });
}

function openProModal() {
  $("vaProModal")?.classList.remove("hidden");
  refreshIcons();
}

function closeProModal() {
  $("vaProModal")?.classList.add("hidden");
}

async function startProPayment() {
  await startPaymentOrder({
    plan: PLAN_AGENT_PRO_MONTHLY,
    buttonId: "vaBuyProBtn",
    fallbackText: "Nâng Cấp Ngay",
    loadingText: "Đang tạo QR...",
    unauthText: "Bạn cần đăng nhập trước khi nâng cấp Agent Pro.",
    readyText: "Quét QR hoặc chuyển khoản đúng nội dung bên dưới.",
  });
}

async function startCreditPayment() {
  await startPaymentOrder({
    plan: PLAN_CREDITS_100,
    buttonId: "vaTopUpCreditBtn",
    fallbackText: "Nạp 50.000đ",
    loadingText: "Đang tạo QR...",
    unauthText: "Bạn cần đăng nhập trước khi nạp Credits.",
    readyText: "Quét QR hoặc chuyển khoản đúng nội dung bên dưới để nạp 100 Credits.",
  });
}

async function startPaymentOrder({ plan, buttonId, fallbackText, loadingText, unauthText, readyText }) {
  if (!state.auth?.token) {
    renderPaymentPanel({
      statusText: unauthText,
      isError: true,
    });
    window.parent?.postMessage({ type: "homevalue:open-auth" }, "*");
    return;
  }

  const btn = $(buttonId);
  const originalText = btn?.textContent || fallbackText;
  if (btn) {
    btn.textContent = loadingText;
    btn.disabled = true;
  }
  try {
    const order = await apiPost("/payments/pro-order", { plan });
    state.activePaymentOrder = order;
    renderPaymentPanel({ order, statusText: readyText });
    startPaymentPolling(order.order_code);
  } catch (error) {
    renderPaymentPanel({ statusText: error.message, isError: true });
  } finally {
    if (btn) {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  }
}

function renderPaymentPanel({ order = null, statusText = "", isError = false } = {}) {
  let panel = $("vaPaymentPanel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "vaPaymentPanel";
    panel.className = "payment-panel";
    document.querySelector("#vaProModal .va-modal-content")?.append(panel);
  }
  panel.textContent = "";

  const status = document.createElement("p");
  status.className = `payment-status${isError ? " is-error" : ""}`;
  status.textContent = statusText || "Đang chờ thanh toán.";
  panel.append(status);

  if (!order) return;

  const layout = document.createElement("div");
  layout.className = "payment-layout";

  const image = document.createElement("img");
  image.className = "payment-qr";
  image.alt = "QR thanh toán VietQR";
  image.src = order.qr_image_url;

  const info = document.createElement("dl");
  info.className = "payment-info";
  [
    ["Gói", paymentPlanLabel(order.plan)],
    ["Số tiền", formatVnd(order.amount_vnd)],
    ...(order.credits_added ? [["Credit nhận", `${order.credits_added} Credits`]] : []),
    ["Ngân hàng", `MBBank (${order.bank_bin})`],
    ["Số tài khoản", order.bank_account_no],
    ["Tên tài khoản", order.bank_account_name],
    ["Nội dung", order.transfer_content],
    ["Trạng thái", paymentStatusLabel(order.status)],
  ].forEach(([label, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value || "-";
    info.append(dt, dd);
  });

  const checkBtn = document.createElement("button");
  checkBtn.type = "button";
  checkBtn.className = "primary-button";
  checkBtn.textContent = "Tôi đã chuyển khoản - kiểm tra";
  checkBtn.disabled = order.status !== "pending";
  checkBtn.addEventListener("click", () => checkPaymentOrder(order.order_code, true));
  info.append(checkBtn);

  layout.append(image, info);
  panel.append(layout);
}

function startPaymentPolling(orderCode) {
  stopPaymentPolling();
  state.paymentPollOrderCode = orderCode;
  schedulePaymentPoll(orderCode, 10000);
}

function schedulePaymentPoll(orderCode, delayMs = 12000) {
  if (state.paymentPollOrderCode !== orderCode) return;
  if (state.paymentPollTimer) window.clearTimeout(state.paymentPollTimer);
  state.paymentPollTimer = window.setTimeout(() => checkPaymentOrder(orderCode, false), delayMs);
}

function stopPaymentPolling() {
  if (state.paymentPollTimer) {
    window.clearTimeout(state.paymentPollTimer);
    state.paymentPollTimer = null;
  }
  state.paymentPollOrderCode = null;
}

async function checkPaymentOrder(orderCode, manual = false) {
  if (state.paymentCheckInFlight) {
    if (manual) {
      renderPaymentPanel({
        order: state.activePaymentOrder,
        statusText: "Đang kiểm tra giao dịch, vui lòng chờ vài giây.",
      });
    }
    return;
  }
  state.paymentCheckInFlight = true;
  let shouldContinuePolling = false;
  try {
    const order = await apiPost(`/payments/${encodeURIComponent(orderCode)}/check`, {});
    state.activePaymentOrder = order;
    if (order.status === "paid") {
      stopPaymentPolling();
      markPaidOrder(order);
      renderPaymentPanel({ order, statusText: paidOrderMessage(order) });
      return;
    }
    if (order.status === "expired") {
      stopPaymentPolling();
      renderPaymentPanel({ order, statusText: "Mã QR đã hết hạn. Tạo đơn mới để thanh toán.", isError: true });
      return;
    }
    shouldContinuePolling = state.paymentPollOrderCode === orderCode;
    renderPaymentPanel({
      order,
      statusText: manual ? "Chưa tìm thấy giao dịch phù hợp. Kiểm tra lại sau vài giây." : "Đang chờ thanh toán.",
    });
  } catch (error) {
    shouldContinuePolling = !manual && state.paymentPollOrderCode === orderCode;
    if (manual) {
      renderPaymentPanel({
        order: state.activePaymentOrder,
        statusText: error.message,
        isError: true,
      });
    }
  } finally {
    state.paymentCheckInFlight = false;
    if (shouldContinuePolling && state.paymentPollOrderCode === orderCode) {
      schedulePaymentPoll(orderCode);
    }
  }
}

function markPaidOrder(order) {
  if (order.plan === PLAN_CREDITS_100) {
    markCreditPaid(order);
    return;
  }
  markProPaid(order);
}

function markProPaid(order) {
  state.isPremium = true;
  localStorage.setItem("homevalue_pro", "1");
  if (state.auth?.user) {
    state.auth.user.is_pro = true;
    state.auth.user.pro_expires_at = order.pro_expires_at || state.auth.user.pro_expires_at;
    localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(state.auth));
  }
  updateCreditUI();
  window.parent?.postMessage({ type: "homevalue:auth-changed" }, "*");
}

function markCreditPaid(order) {
  const added = Number(order.credits_added || 100);
  const serverBalance = Number(order.credit_balance);
  state.credits = Number.isFinite(serverBalance) ? serverBalance : state.credits + added;
  localStorage.setItem("homevalue_credits", String(state.credits));
  if (state.auth?.user) {
    state.auth.user.credit_balance = state.credits;
    localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(state.auth));
  }
  updateCreditUI();
  window.parent?.postMessage({ type: "homevalue:auth-changed" }, "*");
}

function paidOrderMessage(order) {
  if (order.plan === PLAN_CREDITS_100) {
    const added = Number(order.credits_added || 100);
    return `Thanh toán thành công. ${added} Credits đã được cộng vào ví.`;
  }
  return "Thanh toán thành công. Agent Pro đã được kích hoạt.";
}

function paymentPlanLabel(plan) {
  return {
    [PLAN_AGENT_PRO_MONTHLY]: "Agent Pro 1 tháng",
    [PLAN_CREDITS_100]: "Gói 100 Credits",
  }[plan] || plan || "-";
}

function paymentStatusLabel(status) {
  return {
    pending: "Đang chờ",
    paid: "Đã thanh toán",
    expired: "Hết hạn",
  }[status] || status || "-";
}

function formatVnd(value) {
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(Number(value) || 0);
}

function formatInteger(value) {
  return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(Number(value) || 0);
}

function formatNumber(value) {
  return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 }).format(Number(value) || 0);
}

function isAuthUserPro(user) {
  if (!user) return false;
  if (user.is_pro === true) return true;
  if (!user.pro_expires_at) return false;
  const expires = new Date(user.pro_expires_at);
  return Number.isFinite(expires.getTime()) && expires.getTime() > Date.now();
}

function applyPremiumFromAuth() {
  state.isPremium = isAuthUserPro(state.auth?.user);
  if (state.isPremium) {
    localStorage.setItem("homevalue_pro", "1");
  } else {
    localStorage.removeItem("homevalue_pro");
  }
}

function applyCreditsFromAuth() {
  const balance = Number(state.auth?.user?.credit_balance);
  if (!Number.isFinite(balance)) return;
  state.credits = Math.max(0, Math.floor(balance));
  localStorage.setItem("homevalue_credits", String(state.credits));
}

function initialCredits(user) {
  const balance = Number(user?.credit_balance);
  if (Number.isFinite(balance)) return Math.max(0, Math.floor(balance));
  const stored = Number.parseInt(localStorage.getItem("homevalue_credits") || "5", 10);
  return Number.isFinite(stored) ? Math.max(0, stored) : 5;
}

async function boot() {
  setApiStatus("wait", "Đang kiểm tra");
  const ok = await healthCheck();
  await syncAuthProfile();
  setApiStatus(ok ? "ok" : "bad", ok ? "API sẵn sàng" : "API lỗi");
  refreshIcons();
}

async function runChat(message, options = {}) {
  showTyping();
  try {
    const body = { message, style: "prose" };
    const context = options.context || state.pendingChatContext || state.conversationContext;
    if (context) {
      body.context = context;
    }
    if (options.action) {
      body.action = options.action;
      body.idempotency_key = options.idempotencyKey || newIdempotencyKey(options.action);
    }
    const response = await apiPost("/chat", body);
    hideTyping();
    applyServerEntitlements(response);

    updateConversationContext(response);
    updatePendingChatContext(response);
    appendMessage("bot", response.answer || "Mình chưa rõ câu hỏi, bạn thử lại nhé.", {
      missingFields: response.missing_fields || [],
      pendingContext: state.pendingChatContext,
      conversationContext: state.conversationContext,
      intent: response.intent || null,
      data: chatDataForStorage(response),
    });
    handleResponseUi(response);
  } catch (error) {
    hideTyping();
    appendMessage("bot", `Xin lỗi, có lỗi khi xử lý: ${error.message}`);
  }
}

function applyServerEntitlements(response) {
  const entitlements = response?.entitlements || {};
  if (typeof response?.plan === "string") {
    state.isPremium = response.plan === "agent_pro" || entitlements.is_pro === true;
  } else if (entitlements.is_pro === true) {
    state.isPremium = true;
  }
  const balanceAfter = Number(response?.credits?.balance_after);
  if (Number.isFinite(balanceAfter)) {
    state.credits = Math.max(0, Math.floor(balanceAfter));
  } else if (Number.isFinite(Number(entitlements.credit_balance))) {
    state.credits = Math.max(0, Math.floor(Number(entitlements.credit_balance)));
  }
  if (state.auth?.user) {
    state.auth.user.credit_balance = state.credits;
    state.auth.user.is_pro = state.isPremium;
    localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(state.auth));
  }
  localStorage.setItem("homevalue_credits", String(state.credits));
  updateCreditUI();
}

function handleResponseUi(response) {
  const ui = response?.ui || {};
  if (ui.open_pricing) openProModal();
  if (ui.login_required) window.parent?.postMessage({ type: "homevalue:open-auth" }, "*");
}

function newIdempotencyKey(action) {
  return `${action}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

// ===== Sessions (đồng bộ với dashboard) =====
function chatStoreKey() {
  return state.auth?.user?.id ? `${CHAT_SESSIONS_KEY}:user:${state.auth.user.id}` : CHAT_SESSIONS_KEY;
}

function newSessionId() {
  return `s_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function sanitizeEntries(raw) {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((e) => e && ["user", "bot"].includes(e.role) && typeof e.text === "string")
    .map((e) => ({
      role: e.role,
      text: e.text,
      missingFields: Array.isArray(e.missingFields) ? e.missingFields : [],
      pendingContext: e.pendingContext && typeof e.pendingContext === "object" ? e.pendingContext : null,
      conversationContext: e.conversationContext && typeof e.conversationContext === "object" ? e.conversationContext : null,
      intent: typeof e.intent === "string" ? e.intent : null,
      data: e.data && typeof e.data === "object" ? e.data : null,
      timestamp: e.timestamp || new Date().toISOString(),
    }))
    .slice(-MAX_CHAT_HISTORY);
}

function loadSessions() {
  let sessions = [];
  try {
    const parsed = JSON.parse(localStorage.getItem(chatStoreKey()) || "[]");
    if (Array.isArray(parsed)) {
      sessions = parsed
        .filter((s) => s && typeof s.id === "string")
        .map((s) => ({
          id: s.id,
          title: typeof s.title === "string" ? s.title : "Phiên chat",
          createdAt: s.createdAt || new Date().toISOString(),
          updatedAt: s.updatedAt || s.createdAt || new Date().toISOString(),
          messages: sanitizeEntries(s.messages),
        }))
        .slice(-MAX_SESSIONS);
    }
  } catch {
    sessions = [];
  }
  state.sessions = sessions;
  if (!sessions.length) {
    createSession({ render: false });
  } else {
    const latest = sessions.reduce((a, b) => (a.updatedAt > b.updatedAt ? a : b));
    state.activeSessionId = latest.id;
    state.chatHistory = latest.messages;
    state.pendingChatContext = latestPendingContextFromHistory();
    state.conversationContext = latestConversationContextFromHistory();
  }
}

function activeSession() {
  return state.sessions.find((s) => s.id === state.activeSessionId) || null;
}

function createSession(options = {}) {
  const session = {
    id: newSessionId(),
    title: "Phiên chat mới",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    messages: [],
  };
  state.sessions.push(session);
  if (state.sessions.length > MAX_SESSIONS) state.sessions = state.sessions.slice(-MAX_SESSIONS);
  state.activeSessionId = session.id;
  state.chatHistory = session.messages;
  state.pendingChatContext = null;
  state.conversationContext = null;
  saveSessions();
  if (options.render !== false) {
    renderSessionList();
    renderChatHistory();
  }
}

function switchSession(sessionId) {
  const session = state.sessions.find((s) => s.id === sessionId);
  if (!session) return;
  state.activeSessionId = session.id;
  state.chatHistory = session.messages;
  state.pendingChatContext = latestPendingContextFromHistory();
  state.conversationContext = latestConversationContextFromHistory();
  renderSessionList();
  renderChatHistory();
  $("vaSidebar").classList.remove("is-open");
}

function deleteActiveSession() {
  const idx = state.sessions.findIndex((s) => s.id === state.activeSessionId);
  if (idx === -1) return;
  state.sessions.splice(idx, 1);
  if (!state.sessions.length) {
    createSession();
    return;
  }
  const latest = state.sessions.reduce((a, b) => (a.updatedAt > b.updatedAt ? a : b));
  state.activeSessionId = latest.id;
  state.chatHistory = latest.messages;
  state.pendingChatContext = latestPendingContextFromHistory();
  state.conversationContext = latestConversationContextFromHistory();
  saveSessions();
  renderSessionList();
  renderChatHistory();
}

function sessionTitleFromHistory(session) {
  const firstUser = session.messages.find((m) => m.role === "user");
  if (firstUser) {
    const t = firstUser.text.trim().replace(/\s+/g, " ");
    return t.length > 40 ? `${t.slice(0, 39)}…` : t;
  }
  return "Phiên chat mới";
}

function saveSessions() {
  const session = activeSession();
  if (session) {
    session.messages = state.chatHistory;
    session.updatedAt = new Date().toISOString();
    if (session.title === "Phiên chat mới" || !session.title) {
      session.title = sessionTitleFromHistory(session);
    }
  }
  try {
    localStorage.setItem(chatStoreKey(), JSON.stringify(state.sessions.slice(-MAX_SESSIONS)));
  } catch {
    // storage có thể bị tắt
  }
}

function latestPendingContextFromHistory() {
  for (let i = state.chatHistory.length - 1; i >= 0; i -= 1) {
    const entry = state.chatHistory[i];
    if (entry.role === "user") return null;
    if (entry.pendingContext?.pending_intent) return entry.pendingContext;
  }
  return null;
}

function latestConversationContextFromHistory() {
  for (let i = state.chatHistory.length - 1; i >= 0; i -= 1) {
    const entry = state.chatHistory[i];
    if (entry.conversationContext?.extracted) return entry.conversationContext;
  }
  return null;
}

function updateConversationContext(response) {
  if (response?.context && typeof response.context === "object" && response.context.extracted) {
    state.conversationContext = response.context;
    return;
  }
  if (response?.extracted && typeof response.extracted === "object" && Object.keys(response.extracted).length) {
    state.conversationContext = {
      pending_intent: null,
      missing_fields: [],
      extracted: response.extracted,
    };
  }
}

function updatePendingChatContext(response) {
  const missing = Array.isArray(response.missing_fields) ? response.missing_fields : [];
  if (!missing.length || !response.intent) {
    state.pendingChatContext = null;
    return;
  }
  state.pendingChatContext = {
    pending_intent: response.intent,
    missing_fields: missing,
    extracted: response.extracted || {},
  };
}

function reloadAuthScope() {
  const previousKey = chatStoreKey();
  state.auth = loadAuthSession();
  applyPremiumFromAuth();
  applyCreditsFromAuth();
  updateCreditUI();
  const nextKey = chatStoreKey();
  if (previousKey !== nextKey) {
    loadSessions();
    renderSessionList();
    renderChatHistory();
  }
  renderUserScope();
  syncAuthProfile();
}

// ===== Render =====
function renderUserScope() {
  const box = $("vaUserScope");
  if (!box) return;
  box.textContent = "";

  const kicker = document.createElement("span");
  kicker.className = "va-user-kicker";
  kicker.textContent = "Lưu phiên";

  const name = document.createElement("strong");
  const note = document.createElement("small");
  const user = state.auth?.user;
  if (user?.name || user?.email) {
    name.textContent = user.name || user.email;
    note.textContent = user.email ? `Theo tài khoản ${user.email}` : "Theo tài khoản đang đăng nhập";
  } else {
    name.textContent = "Khách";
    note.textContent = "Lưu riêng trên trình duyệt này";
  }

  box.append(kicker, name, note);
}

function renderSessionList() {
  const list = $("vaSessionList");
  list.textContent = "";
  const ordered = [...state.sessions].sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1));
  ordered.forEach((session) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "va-session-item" + (session.id === state.activeSessionId ? " is-active" : "");
    const title = document.createElement("span");
    title.className = "va-session-title";
    title.textContent = session.title || "Phiên chat";
    const time = document.createElement("span");
    time.className = "va-session-time";
    time.textContent = formatMessageTime(session.updatedAt);
    item.append(title, time);
    item.addEventListener("click", () => switchSession(session.id));
    list.append(item);
  });
}

function appendMessage(role, text, options = {}) {
  const entry = {
    role,
    text,
    missingFields: options.missingFields || [],
    pendingContext: options.pendingContext || null,
    conversationContext: options.conversationContext || null,
    intent: options.intent || null,
    data: options.data || null,
    timestamp: new Date().toISOString(),
  };
  renderChatEntry(entry);
  state.chatHistory.push(entry);
  if (state.chatHistory.length > MAX_CHAT_HISTORY) {
    state.chatHistory = state.chatHistory.slice(-MAX_CHAT_HISTORY);
    const s = activeSession();
    if (s) s.messages = state.chatHistory;
  }
  saveSessions();
  renderSessionList();
  updatePdfButtonState();
}

function renderChatHistory() {
  const log = $("vaChatLog");
  log.textContent = "";
  if (!state.chatHistory.length) {
    renderIntro();
  } else {
    state.chatHistory.forEach((entry) => renderChatEntry(entry));
  }
  state.pendingChatContext = latestPendingContextFromHistory();
  state.conversationContext = latestConversationContextFromHistory();
  updatePdfButtonState();
  scrollToBottom();
}

function renderIntro() {
  const intro = document.createElement("div");
  intro.className = "va-intro";
  const h = document.createElement("h2");
  h.textContent = "Mình giúp gì cho bạn?";
  const p = document.createElement("p");
  p.textContent = "Hỏi về định giá bán/thuê, xu hướng giá hoặc tiện ích quanh căn ở các dự án Vinhomes Hà Nội.";
  const chips = document.createElement("div");
  chips.className = "va-chips";
  [
    "Định giá bán căn hộ Vinhomes Smart City 54m2 2PN full nội thất",
    "Giá thuê căn hộ Vinhomes Ocean Park 2PN",
    "Xu hướng giá Ocean Park căn hộ bán",
    "Tiện ích quanh Vinhomes Smart City",
  ].forEach((prompt) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = prompt;
    b.addEventListener("click", () => {
      $("vaChatMessage").value = prompt;
      autoSizeTextarea();
      $("vaChatMessage").focus();
    });
    chips.append(b);
  });
  intro.append(h, p, chips);
  $("vaChatLog").append(intro);
}

function renderChatEntry(entry) {
  const intro = $("vaChatLog").querySelector(".va-intro");
  if (intro) intro.remove();

  const wrapper = document.createElement("article");
  wrapper.className = `va-message ${entry.role}`;
  const avatar = document.createElement("span");
  avatar.className = "va-avatar";
  if (entry.role === "bot") {
    avatar.innerHTML = '<i data-lucide="bot"></i>';
  } else {
    const savedAvatar = localStorage.getItem("homevalue_avatar");
    if (savedAvatar) {
      avatar.innerHTML = `<img src="${savedAvatar}" alt="Bạn" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover; border: 2px solid transparent;" />`;
      avatar.style.background = "transparent";
      if (state.isPremium) {
        avatar.innerHTML = `<img src="${savedAvatar}" alt="Bạn" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover; box-shadow: 0 0 0 2px #fff, 0 0 0 4px #D4AF37;" />
        <div style="position: absolute; top: -4px; right: -4px; width: 14px; height: 14px; background: linear-gradient(135deg, #FFDF00, #D4AF37); border-radius: 50%; display: flex; justify-content: center; align-items: center; box-shadow: 0 1px 4px rgba(0,0,0,0.3); z-index: 10;"><i data-lucide="crown" style="width: 8px; height: 8px; fill: white; color: white;"></i></div>`;
        avatar.style.overflow = "visible";
      } else {
        avatar.style.overflow = "hidden";
      }
    } else {
      avatar.textContent = "Bạn";
      avatar.style.background = "";
      avatar.style.overflow = "hidden";
    }
  }
  const bubble = document.createElement("div");
  bubble.className = "va-bubble";
  renderMessageContent(bubble, entry.text, entry.role, entry);
  const shouldShowAmenityPanel = entry.role === "bot" && entry.intent === "amenity";
  if (shouldShowAmenityPanel && entry.data?.amenity_advice) {
    bubble.append(buildAmenitySearchPanel(entry.data.amenity_advice));
  }
  if (shouldShowAmenityPanel && entry.data?.enrichment?.maps && !entry.data?.amenity_advice) {
    bubble.append(buildAmenitySearchPanel(entry.data.enrichment.maps));
  }
  if (entry.role === "bot" && entry.data?.enrichment) {
    const panel = buildProInsightPanel(entry.data.enrichment);
    if (panel) bubble.append(panel);
  }
  if (entry.role === "bot" && Array.isArray(entry.data?.ui?.actions) && entry.data.ui.actions.length) {
    bubble.append(buildChatActionPanel(entry.data.ui.actions));
  }

  if (Array.isArray(entry.missingFields) && entry.missingFields.length && !hasGuidanceData(entry)) {
    const list = document.createElement("ul");
    list.className = "missing-list";
    entry.missingFields.forEach((f) => {
      const li = document.createElement("li");
      li.textContent = missingFieldLabel(f);
      list.append(li);
    });
    bubble.append(list);
  }

  const meta = document.createElement("span");
  meta.className = "message-meta";
  meta.textContent = formatMessageTime(entry.timestamp);
  bubble.append(meta);

  wrapper.append(avatar, bubble);
  $("vaChatLog").append(wrapper);
  refreshIcons();
  scrollToBottom();
}

const AMENITY_LABELS = new Set([
  "giao thông", "giao thong", "siêu thị", "sieu thi", "trường học", "truong hoc",
  "y tế", "y te", "ăn uống mua sắm", "công viên", "cong vien", "mua sắm", "giải trí", "tiện ích",
]);

function renderMessageContent(container, text, role, entry = {}) {
  const rawLines = String(text || "")
    .split(/\r?\n/)
    .flatMap(splitInlineFactorLine)
    .map((l) => l.trim())
    .filter(Boolean);

  if (role !== "bot" || !rawLines.length) {
    container.textContent = text;
    return;
  }

  if (hasGuidanceData(entry)) {
    renderGuidanceReport(container, entry);
    return;
  }

  const lines = rawLines.map((line) => {
    const isBullet = /^[-*•]\s+/.test(line);
    const clean = line.replace(/^[-*•]\s+/, "").trim();
    const kv = clean.match(/^([^:]{2,64}):\s*(.+)$/);
    const labelText = kv ? kv[1].trim() : "";
    const isAmenity = Boolean(kv && !/^[+\-]/.test(labelText) && AMENITY_LABELS.has(labelText.toLowerCase()));

    // Yếu tố ảnh hưởng giá. Dấu +/- có thể nằm ở dòng gốc ("+ Nhãn: ...")
    // hoặc đã bị tách thành bullet ("- " → mất dấu). Bắt cả hai trường hợp.
    const signedFactor = clean.match(/^([+\-])\s*([^:]{2,64}):\s*(.+)$/);
    const bulletMinus = /^-\s+/.test(line); // dòng gốc bắt đầu bằng "- "
    let factorSign = null;
    let factorLabel = null;
    let factorValue = null;
    if (signedFactor) {
      factorSign = signedFactor[1];
      factorLabel = signedFactor[2].trim();
      factorValue = signedFactor[3].trim();
    } else if (!isAmenity && kv && kv[2].trim().length > 24) {
      // KV mô tả dài, không phải tiện ích → coi là yếu tố. Dấu suy từ bullet gốc.
      factorSign = bulletMinus ? "-" : "+";
      factorLabel = labelText;
      factorValue = kv[2].trim();
    }

    return {
      clean,
      isBullet,
      label: isAmenity ? labelText : null,
      value: isAmenity ? kv[2].trim() : null,
      factorSign,
      factorLabel,
      factorValue,
      summaryLabel: kv && !isAmenity && !factorLabel ? labelText : null,
      summaryValue: kv && !isAmenity && !factorLabel ? kv[2].trim() : null,
    };
  });

  let i = 0;
  while (i < lines.length) {
    const markdownTable = parseMarkdownTable(rawLines, i);
    if (markdownTable) {
      container.append(buildMarkdownTable(markdownTable));
      i = markdownTable.nextIndex;
      continue;
    }

    const line = lines[i];

    // Bảng tóm tắt các dòng "Nhãn: giá trị" như giá, độ tin cậy, mẫu tính toán.
    if (line.summaryLabel) {
      let j = i;
      const rows = [];
      while (j < lines.length && lines[j].summaryLabel) {
        rows.push(lines[j]);
        j += 1;
      }
      if (rows.length >= 2) {
        container.append(buildSummaryTable(rows));
      } else {
        appendParagraphOrReport(container, `${rows[0].summaryLabel}: ${rows[0].summaryValue}`);
      }
      i = j;
      continue;
    }

    // Bảng tiện ích
    if (line.label) {
      let j = i;
      const rows = [];
      while (j < lines.length && lines[j].label) {
        rows.push(lines[j]);
        j += 1;
      }
      container.append(buildAmenityTable(rows));
      i = j;
      continue;
    }

    // Bảng yếu tố ảnh hưởng giá (>=2 dòng +/- "Nhãn: mô tả")
    if (line.factorLabel) {
      let j = i;
      const rows = [];
      while (j < lines.length && lines[j].factorLabel) {
        rows.push(lines[j]);
        j += 1;
      }
      if (rows.length >= 1) {
        container.append(buildFactorTable(rows));
        i = j;
        continue;
      }
    }

    if (line.isBullet) {
      let j = i;
      const items = [];
      while (
        j < lines.length &&
        lines[j].isBullet &&
        !lines[j].label &&
        !lines[j].factorLabel &&
        !lines[j].summaryLabel
      ) {
        items.push(lines[j].clean);
        j += 1;
      }
      const ul = document.createElement("ul");
      ul.className = "response-list";
      items.forEach((t) => {
        const li = document.createElement("li");
        li.textContent = t;
        ul.append(li);
      });
      container.append(ul);
      i = j;
      continue;
    }

    appendParagraphOrReport(container, line.clean);
    i += 1;
  }
}

function splitInlineFactorLine(line) {
  const text = String(line || "").trim();
  if (!/[+\-]\s*[^:]{2,64}:\s*/.test(text)) return [line];
  const firstFactor = text.search(/[+\-]\s*[^:]{2,64}:\s*/);
  const prefix = firstFactor > 0 ? text.slice(0, firstFactor).trim() : "";
  const factorText = text.slice(firstFactor).trim();
  const parts = factorText
    .split(/(?=\s*[+\-]\s*[^:]{2,64}:\s*)/)
    .map((part) => part.trim())
    .filter(Boolean);
  return prefix ? [prefix, ...parts] : parts;
}

function chatDataForStorage(response) {
  const data = response?.data && typeof response.data === "object" ? response.data : {};
  const stored = {};
  const guidance = data?.missing_field_guidance;
  if (Array.isArray(guidance) && guidance.length) {
    stored.missing_field_guidance = guidance;
    stored.retrieval_suggestions = data.retrieval_suggestions || null;
  }
  if (data.amenity_advice) {
    stored.amenity_advice = data.amenity_advice;
  }
  if (data.agent_tool) {
    stored.agent_tool = data.agent_tool;
  }
  if (response?.enrichment && typeof response.enrichment === "object") {
    stored.enrichment = response.enrichment;
  }
  if (response?.ui && typeof response.ui === "object") {
    stored.ui = response.ui;
  }
  if (response?.credits && typeof response.credits === "object") {
    stored.credits = response.credits;
  }
  if (response?.plan) {
    stored.plan = response.plan;
  }
  if (response?.valuation && typeof response.valuation === "object") {
    stored.valuation_summary = valuationSummaryForStorage(response.valuation);
  }
  return Object.keys(stored).length ? stored : null;
}

function valuationSummaryForStorage(valuation) {
  return {
    project: valuation.project || "",
    purpose: valuation.purpose || "",
    property_type: valuation.property_type || "",
    p50_total_vnd: valuation.p50_total_vnd || null,
    confidence: valuation.confidence || null,
  };
}

function sessionHasValuation() {
  return state.chatHistory.some((entry) => entry.role === "bot" && entry.data?.valuation_summary);
}

function updatePdfButtonState() {
  const button = $("vaExportPdfBtn");
  if (!button) return;
  if (!state.isPremium) {
    button.hidden = true;
    button.disabled = true;
    button.setAttribute("aria-hidden", "true");
    return;
  }
  button.hidden = false;
  button.removeAttribute("aria-hidden");
  const enabled = sessionHasValuation();
  button.disabled = !enabled;
  button.title = enabled ? "Xuất Báo Cáo PDF" : "Có kết quả định giá trước khi xuất PDF";
}

function hasGuidanceData(entry) {
  return (
    (Array.isArray(entry?.data?.missing_field_guidance) && entry.data.missing_field_guidance.length > 0) ||
    (Array.isArray(entry?.missingFields) && entry.missingFields.length > 0 && looksLikeMissingInfoAnswer(entry.text))
  );
}

function looksLikeMissingInfoAnswer(text) {
  const value = normalizeText(text || "");
  return value.includes("minh can them") || value.includes("ban co the chon nhap theo cac goi y");
}

function renderGuidanceReport(container, entry) {
  const guidance = guidanceForEntry(entry);
  const isOptions = entry.intent === "options";

  const intro = document.createElement("p");
  intro.className = "response-paragraph";
  intro.textContent = isOptions
    ? "Mình đang hỗ trợ các lựa chọn dưới đây để bạn gửi thông tin định giá."
    : "Mình cần thêm các thông tin dưới đây để dự đoán sát hơn.";
  container.append(intro);

  container.append(buildGuidanceTable(guidance));

  const suggestions = entry.data?.retrieval_suggestions || null;
  if (suggestions && !isOptions) {
    appendSuggestionReport(container, suggestions);
  }

  const example = document.createElement("div");
  example.className = "report-note";
  example.textContent = "Ví dụ: bán căn hộ Vinhomes Smart City 54m2, 2PN, full nội thất.";
  container.append(example);
}

function guidanceForEntry(entry) {
  const guidance = entry?.data?.missing_field_guidance;
  if (Array.isArray(guidance) && guidance.length) return guidance;
  const fields = Array.isArray(entry?.missingFields) ? entry.missingFields : [];
  return fields.map((field) => defaultGuidanceForField(field));
}

function defaultGuidanceForField(field) {
  const optionMap = {
    purpose: {
      field,
      label: "Mục đích",
      options: [
        { value: "sale", label: "bán" },
        { value: "rent", label: "cho thuê" },
      ],
    },
    project: {
      field,
      label: "Dự án",
      options: [
        { value: "vinhomes-ocean-park", label: "Vinhomes Ocean Park" },
        { value: "vinhomes-smart-city", label: "Vinhomes Smart City" },
        { value: "vinhomes-ocean-park-2", label: "Vinhomes Ocean Park 2" },
        { value: "vinhomes-ocean-park-3", label: "Vinhomes Ocean Park 3" },
      ],
    },
    property_type: {
      field,
      label: "Loại hình",
      options: [
        { value: "apartment", label: "căn hộ/chung cư" },
        { value: "villa", label: "biệt thự" },
        { value: "townhouse", label: "liền kề" },
        { value: "shophouse", label: "shophouse" },
        { value: "house", label: "nhà phố" },
        { value: "other", label: "khác/chưa rõ" },
      ],
    },
    area_m2: {
      field,
      label: "Diện tích",
      examples: ["54m2", "75.5m2", "120m2"],
    },
    bedrooms: {
      field,
      label: "Số phòng ngủ",
      options: [
        { value: "0", label: "studio/0PN" },
        { value: "1", label: "1PN" },
        { value: "2", label: "2PN" },
        { value: "3", label: "3PN" },
        { value: "4", label: "4PN+" },
      ],
    },
  };
  return optionMap[field] || { field, label: missingFieldLabel(field), hint: "Bổ sung thông tin này." };
}

function buildGuidanceTable(guidance) {
  const table = document.createElement("table");
  table.className = "chat-table guidance-table";

  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>Trường thông tin</th><th>Gợi ý chọn hoặc nhập</th></tr>";

  const tbody = document.createElement("tbody");
  guidance.forEach((item) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = item.label || missingFieldLabel(item.field);
    const td = document.createElement("td");
    td.append(buildGuidanceValue(item));
    tr.append(th, td);
    tbody.append(tr);
  });

  table.append(thead, tbody);
  return table;
}

function buildGuidanceValue(item) {
  const options = Array.isArray(item.options) ? item.options : [];
  const examples = Array.isArray(item.examples) ? item.examples : [];

  if (options.length) {
    const wrap = document.createElement("div");
    wrap.className = "guidance-options";
    options.forEach((option) => {
      const chip = document.createElement("span");
      chip.className = "guidance-chip";
      chip.textContent = option.label || option.value;
      wrap.append(chip);
    });
    return wrap;
  }

  if (examples.length) {
    const wrap = document.createElement("div");
    wrap.className = "guidance-options";
    examples.forEach((example) => {
      const chip = document.createElement("span");
      chip.className = "guidance-chip muted";
      chip.textContent = example;
      wrap.append(chip);
    });
    return wrap;
  }

  return document.createTextNode(item.hint || "Bổ sung thông tin này.");
}

function appendSuggestionReport(container, suggestions) {
  const projects = Array.isArray(suggestions.nearest_projects) ? suggestions.nearest_projects.slice(0, 3) : [];
  if (projects.length) {
    const heading = document.createElement("p");
    heading.className = "report-heading";
    heading.textContent = "Gợi ý nhanh từ dữ liệu hiện có";
    container.append(heading);
    container.append(buildProjectSuggestionTable(projects));
  }

  const reportItems = [];
  const area = suggestions.area_hint;
  if (area?.range_text || area?.median_text) {
    reportItems.push(
      `Nhóm căn tương tự thường có diện tích khoảng ${area.range_text || "chưa rõ"}, trung vị ${
        area.median_text || "chưa rõ"
      }.`,
    );
  }

  const listings = Array.isArray(suggestions.nearby_listings) ? suggestions.nearby_listings.slice(0, 2) : [];
  listings.forEach((item) => {
    if (!item.project || !item.price_text) return;
    const areaText = item.area_m2 ? `${item.area_m2}m2` : "chưa rõ diện tích";
    const bedroomText = item.bedrooms != null ? `${item.bedrooms}PN` : "chưa rõ PN";
    reportItems.push(`${item.project}: mẫu gần ${areaText}, ${bedroomText}, đang quanh ${item.price_text}.`);
  });

  if (reportItems.length) {
    const ul = document.createElement("ul");
    ul.className = "response-list report-list";
    reportItems.forEach((text) => {
      const li = document.createElement("li");
      li.textContent = text;
      ul.append(li);
    });
    container.append(ul);
  }
}

function buildProjectSuggestionTable(projects) {
  const table = document.createElement("table");
  table.className = "chat-table suggestion-table";
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>Dự án</th><th>Thông tin tham khảo</th></tr>";
  const tbody = document.createElement("tbody");

  projects.forEach((project) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = project.name || project.slug || "Dự án";
    const td = document.createElement("td");
    const details = [];
    if (project.area_range_text) details.push(`diện tích hay gặp ${project.area_range_text}`);
    if (project.median_metric_text) details.push(`mặt bằng khoảng ${project.median_metric_text}`);
    if (project.sample_size) details.push(`${project.sample_size} mẫu`);
    td.textContent = details.join("; ") || "Có dữ liệu tham khảo.";
    tr.append(th, td);
    tbody.append(tr);
  });

  table.append(thead, tbody);
  return table;
}

function appendParagraphOrReport(container, text) {
  const sentences = splitReportSentences(text);
  if (sentences.length <= 2) {
    const p = document.createElement("p");
    p.className = "response-paragraph";
    p.textContent = text;
    container.append(p);
    return;
  }

  const p = document.createElement("p");
  p.className = "response-paragraph";
  p.textContent = sentences[0];
  container.append(p);

  const ul = document.createElement("ul");
  ul.className = "response-list report-list";
  sentences.slice(1).forEach((sentence) => {
    const li = document.createElement("li");
    li.textContent = sentence;
    ul.append(li);
  });
  container.append(ul);
}

function splitReportSentences(text) {
  if (String(text || "").length < 180) return [text];
  return String(text)
    .split(/(?<=[.!?])\s+(?=[0-9A-ZÀ-Ỵ])/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function missingFieldLabel(field) {
  return {
    purpose: "Mục đích",
    project: "Dự án",
    property_type: "Loại hình",
    area_m2: "Diện tích",
    bedrooms: "Số phòng ngủ",
  }[field] || field;
}

function parseMarkdownTable(rawLines, startIndex) {
  if (startIndex + 2 >= rawLines.length) return null;
  const header = splitMarkdownTableCells(rawLines[startIndex]);
  const separator = splitMarkdownTableCells(rawLines[startIndex + 1]);
  if (header.length < 2 || separator.length !== header.length) return null;
  if (!separator.every((cell) => /^:?-{3,}:?$/.test(cell))) return null;

  const rows = [];
  let index = startIndex + 2;
  while (index < rawLines.length) {
    const cells = splitMarkdownTableCells(rawLines[index]);
    if (cells.length !== header.length) break;
    rows.push(cells);
    index += 1;
  }
  return rows.length ? { header, rows, nextIndex: index } : null;
}

function splitMarkdownTableCells(line) {
  const normalized = String(line || "").trim();
  if (!normalized.includes("|")) return [];
  return normalized.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function linkify(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  let escaped = div.innerHTML;
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  return escaped.replace(urlRegex, '<a href="$1" target="_blank" rel="noopener noreferrer">Mở bản đồ</a>');
}

function buildMarkdownTable({ header, rows }) {
  const table = document.createElement("table");
  table.className = "chat-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  header.forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    headRow.append(th);
  });
  thead.append(headRow);

  const tbody = document.createElement("tbody");
  rows.forEach((cells) => {
    const tr = document.createElement("tr");
    cells.forEach((value) => {
      const td = document.createElement("td");
      td.innerHTML = linkify(value);
      tr.append(td);
    });
    tbody.append(tr);
  });
  table.append(thead, tbody);
  return table;
}

function buildSummaryTable(rows) {
  const table = document.createElement("table");
  table.className = "chat-table summary-table";
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = row.summaryLabel;
    const td = document.createElement("td");
    td.innerHTML = linkify(row.summaryValue);
    tr.append(th, td);
    tbody.append(tr);
  });
  table.append(tbody);
  return table;
}

function buildAmenityTable(rows) {
  const table = document.createElement("table");
  table.className = "chat-table";
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = row.label;
    const td = document.createElement("td");
    td.innerHTML = linkify(row.value);
    tr.append(th, td);
    tbody.append(tr);
  });
  table.append(tbody);
  return table;
}

function buildAmenitySearchPanel(advice) {
  const panel = document.createElement("section");
  panel.className = "amenity-search-panel";

  const header = document.createElement("div");
  header.className = "amenity-search-head";
  const title = document.createElement("strong");
  title.textContent = "Search tiện ích";
  const location = document.createElement("span");
  location.textContent = advice.location_label || advice.project || "Khu vực đang phân tích";
  header.append(title, location);

  const actions = document.createElement("div");
  actions.className = "amenity-search-actions";
  const baseUrl = safeUrl(advice.base_map_url);
  if (baseUrl) {
    actions.append(buildAmenityLink("Vị trí dự án", baseUrl, "map-pin"));
  }

  const categories = Array.isArray(advice.categories) ? advice.categories : [];
  categories.forEach((category) => {
    const url = safeUrl(category.map_url);
    if (!url) return;
    actions.append(buildAmenityLink(category.label || "Mở map", url, "map"));
  });

  panel.append(header, actions);

  const categoriesWithPlaces = categories.filter((category) => Array.isArray(category.places) && category.places.length);
  if (categoriesWithPlaces.length) {
    const places = document.createElement("div");
    places.className = "amenity-search-places";
    categoriesWithPlaces.slice(0, 4).forEach((category) => {
      const group = document.createElement("div");
      group.className = "amenity-place-group";
      const groupTitle = document.createElement("strong");
      groupTitle.textContent = category.label || "Tiện ích";
      const list = document.createElement("ul");
      category.places.slice(0, 3).forEach((place) => {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = safeUrl(place.maps_url) || safeUrl(category.map_url) || "#";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = place.name || "Mở trên Google Maps";
        const meta = amenityPlaceMetaText(place);
        if (meta) {
          const small = document.createElement("small");
          small.textContent = meta;
          item.append(link, small);
        } else {
          item.append(link);
        }
        list.append(item);
      });
      group.append(groupTitle, list);
      places.append(group);
    });
    panel.append(places);
  }

  return panel;
}

function buildProInsightPanel(enrichment = {}) {
  const hasNews = Array.isArray(enrichment.news?.items) && enrichment.news.items.length;
  const hasOutlook = enrichment.outlook?.summary || enrichment.outlook?.tone || enrichment.outlook?.risk;
  if (!hasNews && !hasOutlook) return null;

  const panel = document.createElement("section");
  panel.className = "pro-insight-panel";

  if (hasOutlook) {
    const card = document.createElement("article");
    card.className = "pro-insight-card outlook-card";
    const title = document.createElement("strong");
    title.innerHTML = '<i data-lucide="sparkles"></i><span>Triển vọng</span>';
    const summary = document.createElement("p");
    summary.textContent = enrichment.outlook.summary || enrichment.outlook.tone || "Có nhận định triển vọng từ dữ liệu bổ sung.";
    card.append(title, summary);
    panel.append(card);
  }

  if (hasNews) {
    const card = document.createElement("article");
    card.className = "pro-insight-card news-card";
    const title = document.createElement("strong");
    title.innerHTML = '<i data-lucide="newspaper"></i><span>Tin tức liên quan</span>';
    const list = document.createElement("ul");
    enrichment.news.items.slice(0, 3).forEach((item) => {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = safeUrl(item.url) || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.title || "Tin liên quan";
      const meta = document.createElement("small");
      meta.textContent = newsMetaText(item);
      li.append(link);
      if (meta.textContent) li.append(meta);
      list.append(li);
    });
    card.append(title, list);
    panel.append(card);
  }

  return panel;
}

function buildChatActionPanel(actions) {
  const panel = document.createElement("div");
  panel.className = "chat-action-panel";
  actions.forEach((action) => {
    const idempotencyKey = action.idempotency_key || newIdempotencyKey(action.type || "chat_action");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-action-button";
    button.innerHTML = '<i data-lucide="map"></i><span></span>';
    button.querySelector("span").textContent = action.label || "Thực hiện";
    button.addEventListener("click", async () => {
      const message = action.message || action.label || "Tiếp tục";
      button.disabled = true;
      appendMessage("user", message);
      try {
        await runChat(message, {
          action: action.type,
          context: action.context || null,
          idempotencyKey,
        });
      } catch {
        button.disabled = false;
      }
    });
    panel.append(button);
  });
  return panel;
}

function buildAmenityLink(label, href, iconName = "map") {
  const link = document.createElement("a");
  link.className = "amenity-search-link";
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.innerHTML = `<i data-lucide="${iconName}"></i><span></span>`;
  link.querySelector("span").textContent = label;
  return link;
}

function amenityPlaceMetaText(place = {}) {
  const parts = [];
  if (Number.isFinite(Number(place.distance_m))) parts.push(`${formatInteger(place.distance_m)} m`);
  if (Number.isFinite(Number(place.rating))) parts.push(`${formatNumber(place.rating)} sao`);
  if (Number.isFinite(Number(place.user_ratings_total))) parts.push(`${formatInteger(place.user_ratings_total)} đánh giá`);
  if (place.address) parts.push(place.address);
  return parts.join(" - ");
}

function safeUrl(value) {
  const url = String(value || "").trim();
  return /^https?:\/\//i.test(url) ? url : "";
}

function newsStatusLabel(value) {
  const labels = {
    completed: "Đã hoàn thành",
    under_construction: "Đang thi công",
    officially_announced: "Đã công bố",
    confirmed: "Đã xác nhận",
    proposed: "Đề xuất/nghiên cứu",
    rumored: "Chưa xác thực",
    unknown: "Chưa rõ trạng thái",
    reference: "Tin tham khảo",
  };
  return labels[value] || "";
}

function newsProximityText(item = {}) {
  const status = item.proximity_status || "";
  const distance = Number(item.distance_km);
  if (status === "verified_nearby" && Number.isFinite(distance)) {
    return `Cách vị trí định giá ${formatNumber(distance)} km`;
  }
  if (status === "same_area_unverified") return "Cùng khu vực, chưa xác minh khoảng cách";
  if (status === "outside_radius") return "Ngoài bán kính phân tích";
  if (status === "unverified") return "Chưa xác minh khoảng cách";
  return "";
}

function newsMetaText(item = {}) {
  return [
    item.source || item.source_name,
    item.published_text,
    newsStatusLabel(item.event_status || item.status),
    newsProximityText(item),
  ]
    .filter(Boolean)
    .join(" - ");
}

function buildFactorTable(rows) {
  const grid = document.createElement("section");
  grid.className = "factor-card-grid";
  rows.forEach((row) => {
    const card = document.createElement("article");
    card.className = `factor-card ${row.factorSign === "+" ? "is-positive" : "is-negative"}`;
    const head = document.createElement("div");
    head.className = "factor-card-head";
    const sign = document.createElement("span");
    sign.className = `factor-sign ${row.factorSign === "+" ? "up" : "down"}`;
    sign.textContent = row.factorSign === "+" ? "▲" : "▼";
    const title = document.createElement("strong");
    title.textContent = row.factorLabel;
    const body = document.createElement("p");
    body.innerHTML = linkify(row.factorValue);
    head.append(sign, title);
    card.append(head, body);
    grid.append(card);
  });
  return grid;
}

function showTyping() {
  hideTyping();
  const wrapper = document.createElement("article");
  wrapper.className = "va-message bot";
  wrapper.id = "vaTyping";
  const avatar = document.createElement("span");
  avatar.className = "va-avatar";
  avatar.innerHTML = '<i data-lucide="bot"></i>';
  const bubble = document.createElement("div");
  bubble.className = "va-bubble typing-bubble";
  const dots = document.createElement("span");
  dots.className = "typing-dots";
  dots.innerHTML = "<span></span><span></span><span></span>";
  const label = document.createElement("span");
  label.className = "typing-label";
  label.textContent = "Trợ lý đang soạn câu trả lời";
  bubble.append(dots, label);
  wrapper.append(avatar, bubble);
  $("vaChatLog").append(wrapper);
  refreshIcons();
  scrollToBottom();
}

function hideTyping() {
  const el = $("vaTyping");
  if (el) el.remove();
}

// ===== Helpers =====
function autoSizeTextarea() {
  const ta = $("vaChatMessage");
  ta.style.height = "auto";
  ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
}

function scrollToBottom() {
  const log = $("vaChatLog");
  log.scrollTop = log.scrollHeight;
}

function setApiStatus(kind, text) {
  const el = $("vaApiStatus");
  el.className = `status-pill status-${kind}`;
  el.textContent = text;
}

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function formatMessageTime(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  }).format(d);
}

function normalizeText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function loadAuthSession() {
  try {
    const parsed = JSON.parse(localStorage.getItem(AUTH_SESSION_KEY) || "null");
    if (!parsed || typeof parsed !== "object" || typeof parsed.token !== "string") return null;
    if (!parsed.user || typeof parsed.user !== "object") return null;
    return parsed;
  } catch {
    return null;
  }
}

// ===== API =====
async function apiGet(path) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let resp;
  try {
    const headers = {};
    if (state.auth?.token) headers.Authorization = `Bearer ${state.auth.token}`;
    resp = await fetch(`${state.apiBase}${path}`, { headers, signal: controller.signal });
  } catch (error) {
    window.clearTimeout(timer);
    throw new Error(error.name === "AbortError" ? "Phản hồi quá lâu, thử lại nhé." : "Không kết nối được API.");
  }
  window.clearTimeout(timer);
  return parseApiResponse(resp);
}

async function apiPost(path, body) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let resp;
  try {
    const headers = { "Content-Type": "application/json" };
    if (state.auth?.token) headers.Authorization = `Bearer ${state.auth.token}`;
    resp = await fetch(`${state.apiBase}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    window.clearTimeout(timer);
    throw new Error(error.name === "AbortError" ? "Phản hồi quá lâu, thử lại nhé." : "Không kết nối được API.");
  }
  window.clearTimeout(timer);
  return parseApiResponse(resp);
}

async function parseApiResponse(resp) {
  const text = await resp.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!resp.ok) {
    const detail = payload?.detail || payload || resp.statusText;
    throw new Error(Array.isArray(detail) ? detail.map((d) => d.msg || d).join(", ") : detail);
  }
  return payload;
}

async function syncAuthProfile() {
  if (!state.auth?.token) {
    applyPremiumFromAuth();
    updateCreditUI();
    return;
  }
  try {
    const user = await apiGet("/auth/me");
    state.auth.user = user;
    localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(state.auth));
  } catch {
    // Giữ phiên local hiện tại; endpoint auth có thể tạm thời lỗi mạng.
  }
  applyPremiumFromAuth();
  applyCreditsFromAuth();
  updateCreditUI();
}

async function healthCheck() {
  try {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(`${state.apiBase}/health`, { signal: controller.signal });
    window.clearTimeout(timer);
    return resp.ok;
  } catch {
    return false;
  }
}

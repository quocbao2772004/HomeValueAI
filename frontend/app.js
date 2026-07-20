const PRODUCTION_API_BASE = "/api";
const LOCAL_API_BASE = "http://127.0.0.1:8000";
const LOCAL_API_BASE_BY_PORT = {
  2707: "/api",
};

const state = {
  apiBase: initialApiBase(),
  projects: [],
  latestValuation: null,
  latestEvaluation: null,
  latestTrends: null,
  latestNews: null,
  latestAmenityAdvice: null,
  activeComparable: null,
  pendingChatContext: null,
  conversationContext: null,
  chatHistory: [],
  auth: loadAuthSession(),
  authMode: "login",
};

const CHAT_HISTORY_KEY = "homevalue_chat_history";
const AUTH_SESSION_KEY = "homevalue_auth_session";
const MAX_CHAT_HISTORY = 120;

const purposeLabels = {
  sale: "Bán",
  rent: "Thuê",
};

const propertyTypeLabels = {
  apartment: "Căn hộ",
  villa: "Biệt thự",
  townhouse: "Liền kề",
  shophouse: "Shophouse",
  house: "Nhà phố",
  other: "Khác",
};

const confidenceLabels = {
  low: "Thấp",
  medium: "Trung bình",
  high: "Cao",
};

const trendLabels = {
  "1m": "1 tháng",
  "3m": "3 tháng",
  "6m": "6 tháng",
  "12m": "12 tháng",
};

const structureData = {
  "vinhomes-smart-city": {
    subdivisions: ["The Sapphire", "The Miami", "The Sakura", "The Tonkin", "Masteri West Heights"],
    towers: ["S1.01", "S1.02", "S1.03", "S1.05", "S1.06", "S2.01", "S2.02", "S2.03", "S2.05", "S3.01", "S3.02", "S3.03", "SA2", "SA3", "GS1", "GS2", "GS3", "TK1", "TK2"]
  },
  "vinhomes-ocean-park": {
    subdivisions: ["The Sapphire", "The Zenpark", "The Pavilion", "Masteri Waterfront", "The Ocean View"],
    towers: ["S1.01", "S1.02", "S1.03", "S1.05", "S1.06", "S1.07", "S1.08", "S1.09", "S1.10", "S1.11", "S1.12", "S2.01", "S2.02", "S2.03", "S2.05", "S2.06", "S2.07", "S2.08", "S2.09", "S2.10", "S2.11", "S2.12", "S2.15", "S2.16", "S2.17", "R1.01", "R1.02", "R1.03", "R1.05", "P1", "P2", "P3", "P4"]
  },
  "vinhomes-ocean-park-2": {
    subdivisions: ["Chà Là", "Ngọc Trai", "San Hô", "Sao Biển", "Hải Âu", "Cọ Xanh", "Kinh Đô Ánh Sáng", "Đảo Dừa"],
    towers: []
  },
  "vinhomes-ocean-park-3": {
    subdivisions: ["Thời Đại", "Vịnh Thiên Đường", "Phố Biển", "Ánh Dương", "Hải Đăng", "Vịnh Tây", "Đảo Ngọc"],
    towers: []
  }
};

function updateStructureDropdowns() {
  const project = $("project").value;
  const data = structureData[project] || { subdivisions: [], towers: [] };
  
  const subSelect = $("subdivision");
  if (subSelect) {
    subSelect.innerHTML = '<option value="">Chưa rõ</option>' + 
      data.subdivisions.map(s => `<option value="${s}">${s}</option>`).join("");
  }
    
  const towerSelect = $("tower");
  if (towerSelect) {
    towerSelect.innerHTML = '<option value="">Chưa rõ</option>' + 
      data.towers.map(t => `<option value="${t}">${t}</option>`).join("");
  }
}

function checkFormReadiness() {
  const project = $("project")?.value;
  const area = $("areaM2")?.value.trim();
  const bedrooms = $("bedrooms")?.value.trim();
  const propertyType = $("propertyType")?.value;
  const view = $("view")?.value;
  const furniture = $("furniture")?.value;
  
  if (project && propertyType && area && bedrooms && view && furniture) {
    if ($("labelSubdivision")) $("labelSubdivision").style.display = "block";
    if ($("labelTower")) $("labelTower").style.display = "block";
  } else {
    if ($("labelSubdivision")) $("labelSubdivision").style.display = "none";
    if ($("labelTower")) $("labelTower").style.display = "none";
  }
}

const $ = (id) => document.getElementById(id);

function initialApiBase() {
  const localHostnames = new Set(["127.0.0.1", "localhost", "0.0.0.0", ""]);
  const isLocal = localHostnames.has(window.location.hostname);
  return isLocal ? (LOCAL_API_BASE_BY_PORT[window.location.port] || LOCAL_API_BASE) : PRODUCTION_API_BASE;
}

document.addEventListener("DOMContentLoaded", () => {
  state.chatHistory = loadChatHistory();
  bindEvents();
  refreshAuthUi();
  renderChatHistory();
  drawValuationChart();
  drawMarketSummaryChart();
  renderMapForQuery("Vinhomes Smart City", "Vinhomes Smart City");
  boot();
});

function bindEvents() {
  bindAssistantWidget();
  bindAuthEvents();

  $("samplePrompt").addEventListener("click", () => {
    $("chatMessage").value = "Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất";
    $("chatMessage").focus();
  });

  $("clearChat").addEventListener("click", () => {
    state.chatHistory = [];
    state.pendingChatContext = null;
    state.conversationContext = null;
    saveChatHistory();
    renderChatHistory();
  });

  $("chatMessage").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (typeof $("chatForm").requestSubmit === "function") {
      $("chatForm").requestSubmit();
    } else {
      $("chatForm").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }
  });

  $("resetForm").addEventListener("click", () => {
    $("valuationForm").reset();
    $("areaM2").value = "54.2";
    $("bedrooms").value = "2";
  });

  $("valuationForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = readValuationForm();
    await runValuation(payload);
    await refreshMarket();
  });

  $("chatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = $("chatMessage").value.trim();
    if (!message) return;
    $("chatMessage").value = "";
    appendMessage("user", message);
    await runChat(message);
  });

  $("refreshMarket").addEventListener("click", async () => {
    await refreshMarket();
    await refreshEvaluation();
  });
  $("refreshAmenities").addEventListener("click", async () => {
    await refreshAmenities(state.activeComparable);
  });
  const mapCompSelect = $("mapCompSelect");
  if (mapCompSelect) {
    mapCompSelect.addEventListener("change", async (event) => {
      const index = Number(event.target.value);
      const comp = state.mapComps?.[index];
      if (!comp) return;
      renderMapForComparable(comp);
      await refreshAmenities(comp);
    });
  }
  $("project").addEventListener("change", () => {
    updateStructureDropdowns();
    checkFormReadiness();
    renderMapForQuery(`${currentProjectName()} Hà Nội`, currentProjectName());
    state.activeComparable = null;
    refreshAmenities();
    refreshMarket();
    state.latestNews = null;
  });
  $("propertyType").addEventListener("change", () => {
    checkFormReadiness();
    refreshMarket();
    refreshAmenities(state.activeComparable);
  });
  ["areaM2", "bedrooms", "view", "furniture"].forEach(id => {
    $(id).addEventListener("input", checkFormReadiness);
    $(id).addEventListener("change", checkFormReadiness);
  });
  document.querySelectorAll("input[name='purpose']").forEach((input) => {
    input.addEventListener("change", () => {
      refreshMarket();
      refreshAmenities(state.activeComparable);
      state.latestNews = null;
    });
  });
  
  bindTabs();
}

function bindAssistantWidget() {
  const launcher = $("chatLauncher");
  const widget = $("assistantWidget");
  if (!launcher || !widget) return;

  launcher.addEventListener("click", () => {
    if (widget.hidden) {
      openAssistantWidget();
    } else {
      closeAssistantWidget();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !widget.hidden) closeAssistantWidget(true);
  });

  window.addEventListener("message", (event) => {
    if (event.data?.type === "homevalue:open-auth") {
      openAuthDialog(state.auth ? "account" : "login");
    }
  });
}

function openAssistantWidget() {
  const widget = $("assistantWidget");
  const launcher = $("chatLauncher");
  if (!widget || !launcher) return;
  widget.hidden = false;
  document.body.classList.add("assistant-open");
  launcher.classList.add("is-open");
  launcher.setAttribute("aria-expanded", "true");
  const label = launcher.querySelector(".chat-launcher-label");
  if (label) label.textContent = "Đóng";
  window.setTimeout(() => {
    $("assistantFrame")?.contentWindow?.postMessage({ type: "homevalue:focus-assistant" }, "*");
    notifyAssistantAuthChanged();
  }, 180);
}

function closeAssistantWidget(focusLauncher = false) {
  const widget = $("assistantWidget");
  const launcher = $("chatLauncher");
  if (!widget || !launcher) return;
  widget.hidden = true;
  document.body.classList.remove("assistant-open");
  launcher.classList.remove("is-open");
  launcher.setAttribute("aria-expanded", "false");
  const label = launcher.querySelector(".chat-launcher-label");
  if (label) label.textContent = "Trợ lý";
  if (focusLauncher) launcher.focus();
}

function bindAuthEvents() {
  $("authButton")?.addEventListener("click", () => openAuthDialog(state.auth ? "account" : "login"));
  $("authClose")?.addEventListener("click", closeAuthDialog);
  document.querySelectorAll("[data-auth-close]").forEach((button) => {
    button.addEventListener("click", closeAuthDialog);
  });
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.addEventListener("click", () => setAuthMode(button.dataset.authMode || "login"));
  });
  $("authForm")?.addEventListener("submit", handleAuthSubmit);
  $("authLogout")?.addEventListener("click", () => {
    clearAuthSession();
    closeAuthDialog();
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== AUTH_SESSION_KEY) return;
    state.auth = loadAuthSession();
    reloadUserScopedChat();
    refreshAuthUi();
  });

  const AVATAR_TEMPLATES = [
    "avatars/avatar_male_broker.png",
    "avatars/avatar_female_broker.png",
    "avatars/avatar_eagle_logo.png",
    "avatars/avatar_diamond_logo.png"
  ];

  $("authEditAvatarBtn")?.addEventListener("click", () => {
    const isPremium = isAuthUserPro(state.auth?.user);
    if (!isPremium) {
      alert("Tính năng đổi Avatar cá nhân hóa chỉ dành riêng cho tài khoản Agent Pro! Vui lòng mở trợ lý định giá và nâng cấp để sử dụng.");
      return;
    }
    const grid = $("avatarTemplatesGrid");
    if (grid && grid.children.length === 0) {
      AVATAR_TEMPLATES.forEach(src => {
        const btn = document.createElement("button");
        btn.style.cssText = "width: 100%; aspect-ratio: 1; padding: 0; border: 2px solid transparent; border-radius: 8px; overflow: hidden; cursor: pointer; transition: all 0.2s;";
        btn.innerHTML = `<img src="${src}" style="width: 100%; height: 100%; object-fit: cover;" />`;
        btn.onclick = () => {
          localStorage.setItem("homevalue_avatar", src);
          $("authAvatarImg").src = src;
          notifyAssistantAuthChanged();
          $("avatarPopover").style.display = "none";
        };
        btn.onmouseover = () => btn.style.borderColor = "var(--teal)";
        btn.onmouseout = () => btn.style.borderColor = "transparent";
        grid.appendChild(btn);
      });
    }
    $("avatarPopover").style.display = "block";
  });

  $("closeAvatarPopover")?.addEventListener("click", () => {
    $("avatarPopover").style.display = "none";
  });

  $("authAvatarUploadBtn")?.addEventListener("click", () => {
    $("authAvatarInput")?.click();
    $("avatarPopover").style.display = "none";
  });

  $("authAvatarInput")?.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const dataUrl = evt.target.result;
      localStorage.setItem("homevalue_avatar", dataUrl);
      $("authAvatarImg").src = dataUrl;
      notifyAssistantAuthChanged();
    };
    reader.readAsDataURL(file);
  });
}

function openAuthDialog(mode = "login") {
  const dialog = $("authDialog");
  if (!dialog) return;
  dialog.hidden = false;
  if (!state.auth) setAuthMode(mode === "register" ? "register" : "login");
  refreshAuthUi();
  window.setTimeout(() => {
    const target = state.auth ? $("authLogout") : $("authEmail");
    target?.focus();
  }, 0);
}

function closeAuthDialog() {
  const dialog = $("authDialog");
  if (!dialog) return;
  dialog.hidden = true;
  setAuthMessage("");
}

function setAuthMode(mode) {
  state.authMode = mode === "register" ? "register" : "login";
  const isRegister = state.authMode === "register";
  $("authTitle").textContent = isRegister ? "Đăng ký" : "Đăng nhập";
  $("authNameField").hidden = !isRegister;
  $("authName").required = isRegister;
  $("authPassword").autocomplete = isRegister ? "new-password" : "current-password";
  $("authSubmit").querySelector("span").textContent = isRegister ? "Tạo tài khoản" : "Đăng nhập";
  $("authSubmit").querySelector("i")?.setAttribute("data-lucide", isRegister ? "user-plus" : "log-in");
  if ($("authDemoNote")) $("authDemoNote").hidden = isRegister;
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.authMode === state.authMode);
  });
  setAuthMessage("");
  refreshIcons();
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const isRegister = state.authMode === "register";
  const payload = {
    email: $("authEmail").value.trim(),
    password: $("authPassword").value,
  };
  if (isRegister) payload.name = $("authName").value.trim();

  setPanelLoading("authSubmit", true);
  setAuthMessage(isRegister ? "Đang tạo tài khoản..." : "Đang đăng nhập...");
  try {
    const response = await apiPost(isRegister ? "/auth/register" : "/auth/login", payload);
    saveAuthSession(response);
    setAuthMessage(isRegister ? "Đã tạo tài khoản." : "Đăng nhập thành công.");
    window.setTimeout(closeAuthDialog, 250);
  } catch (error) {
    setAuthMessage(error.message || "Không xử lý được tài khoản.", true);
  } finally {
    setPanelLoading("authSubmit", false);
  }
}

async function syncCurrentUser() {
  if (!state.auth?.token) return;
  try {
    const user = await apiGet("/auth/me");
    state.auth = { ...state.auth, user };
    persistAuthSession();
    refreshAuthUi();
  } catch {
    clearAuthSession({ silent: true });
  }
}

function saveAuthSession(response) {
  const token = response?.access_token || response?.token;
  const user = response?.user;
  if (!token || !user) throw new Error("Phản hồi đăng nhập thiếu token.");
  state.auth = { token, user };
  persistAuthSession();
  reloadUserScopedChat();
  refreshAuthUi();
  notifyAssistantAuthChanged();
}

function persistAuthSession() {
  try {
    if (state.auth) {
      localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(state.auth));
    } else {
      localStorage.removeItem(AUTH_SESSION_KEY);
    }
  } catch {
    // localStorage có thể bị khóa; phiên hiện tại vẫn dùng được trong tab này.
  }
}

function clearAuthSession(options = {}) {
  state.auth = null;
  persistAuthSession();
  reloadUserScopedChat();
  refreshAuthUi();
  if (!options.silent) notifyAssistantAuthChanged();
}

function refreshAuthUi() {
  const user = state.auth?.user;
  const label = $("authButtonLabel");
  const authButton = $("authButton");
  if (label) label.textContent = user ? authButtonLabel(user) : "Đăng nhập";
  if (authButton) {
    authButton.classList.toggle("is-authenticated", Boolean(user));
    authButton.title = user
      ? `${user.name || user.email}${user.email ? ` - ${user.email}` : ""}`
      : "Đăng nhập hoặc quản lý tài khoản";
  }

  const summary = $("authSessionSummary");
  const tabs = document.querySelector(".auth-mode-tabs");
  const form = $("authForm");
  if (summary) summary.hidden = !user;
  if (tabs) tabs.hidden = Boolean(user);
  if (form) form.hidden = Boolean(user);
  if (user) {
    $("authTitle").textContent = "Tài khoản";
    $("authSessionName").textContent = user.name || user.email;
    $("authSessionEmail").textContent = user.email || "";
    const savedAvatar = localStorage.getItem("homevalue_avatar");
    if (savedAvatar) {
      $("authAvatarImg").src = savedAvatar;
    }
    const isPremium = isAuthUserPro(user);
    if (isPremium) {
      $("authAvatarImg").classList.add("pro-avatar-frame");
      if ($("authProBadge")) $("authProBadge").style.display = "flex";
    } else {
      $("authAvatarImg").classList.remove("pro-avatar-frame");
      if ($("authProBadge")) $("authProBadge").style.display = "none";
    }
  } else {
    setAuthMode(state.authMode);
  }
  refreshIcons();
}

function isAuthUserPro(user) {
  if (!user) return false;
  if (user.is_pro === true) return true;
  if (!user.pro_expires_at) return false;
  const expires = new Date(user.pro_expires_at);
  return Number.isFinite(expires.getTime()) && expires.getTime() > Date.now();
}

function setAuthMessage(message, isError = false) {
  const el = $("authMessage");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("is-error", Boolean(isError));
}

function authButtonLabel(user) {
  const raw = user?.name || user?.email || "Tài khoản";
  return String(raw).replace(/\s+/g, " ").trim() || "Tài khoản";
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

function reloadUserScopedChat() {
  state.chatHistory = loadChatHistory();
  state.pendingChatContext = null;
  state.conversationContext = null;
  renderChatHistory();
}

function notifyAssistantAuthChanged() {
  $("assistantFrame")?.contentWindow?.postMessage({ type: "homevalue:auth-changed" }, "*");
}

function bindTabs() {
  const tabsNav = document.querySelector(".tabs-nav");
  if (!tabsNav) return;
  
  tabsNav.addEventListener("click", (event) => {
    const btn = event.target.closest(".tab-btn");
    if (!btn) return;
    
    // Deactivate all
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    
    // Activate target
    btn.classList.add("active");
    const targetId = btn.getAttribute("data-target");
    const panel = document.getElementById(targetId);
    if (panel) panel.classList.add("active");
    refreshPanelAfterTabSwitch(targetId);
  });
}

function refreshPanelAfterTabSwitch(targetId) {
  window.requestAnimationFrame(() => {
    if (targetId === "result-panel") drawValuationChart(state.latestValuation);
    if (targetId === "data-panel") drawMarketSummaryChart(state.latestEvaluation);
    if (targetId === "market-panel") renderTrends(state.latestTrends);
    if (targetId === "news-panel" && !state.latestNews) refreshNews();
  });
}

async function boot() {
  setApiStatus("wait", "Đang kiểm tra");
  try {
    await apiGet("/health");
    setApiStatus("ok", "API sẵn sàng");
    await syncCurrentUser();
    await loadProjects();
    await refreshMarket();
    await refreshEvaluation();
  } catch (error) {
    setApiStatus("bad", "API lỗi");
    appendMessage("bot", `Không kết nối được API: ${error.message}`, { save: false });
  }
  refreshIcons();
}

async function loadProjects() {
  const projects = await apiGet("/projects");
  state.projects = Array.isArray(projects) ? projects : [];
  const select = $("project");
  select.textContent = "";
  if (!state.projects.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Chưa có dự án";
    select.append(option);
    return;
  }

  state.projects.forEach((project) => {
    const option = document.createElement("option");
    option.value = project.slug;
    option.textContent = project.name;
    select.append(option);
  });

  const smartCity = state.projects.find((project) => project.slug === "vinhomes-smart-city");
  if (smartCity) select.value = smartCity.slug;
  
  updateStructureDropdowns();
  checkFormReadiness();
}

async function runChat(message) {
  setPanelLoading("chatLog", true);
  try {
    const requestBody = { message };
    const context = state.pendingChatContext || state.conversationContext;
    if (context) requestBody.context = context;
    const response = await apiPost("/chat", requestBody);
    if (response.extracted) applyExtracted(response.extracted);
    updateConversationContext(response);
    updatePendingChatContext(response);
    appendBotResponse(response);

    if (response.valuation) {
      state.latestValuation = response.valuation;
      renderValuation(response.valuation, { amenityAdvice: response.data?.amenity_advice });
      await refreshMarket();
    } else if (response.data?.windows) {
      state.latestTrends = response.data;
      renderTrends(response.data);
    } else if (response.data?.amenity_advice) {
      renderAmenities(response.data.amenity_advice);
    }
  } catch (error) {
    appendMessage("bot", `Không xử lý được câu hỏi: ${error.message}`);
  } finally {
    setPanelLoading("chatLog", false);
  }
}

async function runValuation(payload) {
  setPanelLoading("runValuation", true);
  try {
    const valuation = await apiPost("/valuation", payload);
    state.latestValuation = valuation;
    renderValuation(valuation);
  } catch (error) {
    appendMessage("bot", `Không định giá được: ${error.message}`);
  } finally {
    setPanelLoading("runValuation", false);
  }
}

async function refreshMarket() {
  const project = $("project").value;
  if (!project) return;
  const purpose = getPurpose();
  const propertyType = $("propertyType").value;
  const params = new URLSearchParams({
    project,
    purpose,
    property_type: propertyType,
  });

  setPanelLoading("refreshMarket", true);
  try {
    const trends = await apiGet(`/market-trends?${params.toString()}`);
    state.latestTrends = trends;
    renderTrends(trends);
  } catch (error) {
    renderTrendError(error.message);
  } finally {
    setPanelLoading("refreshMarket", false);
  }
}

function readValuationForm() {
  const form = new FormData($("valuationForm"));
  const payload = {
    purpose: getPurpose(),
    project: form.get("project"),
    property_type: form.get("property_type"),
    area_m2: Number(form.get("area_m2")),
  };

  addNumber(payload, "bedrooms", form.get("bedrooms"));
  addString(payload, "view", form.get("view"));
  addString(payload, "furniture", form.get("furniture"));
  addString(payload, "subdivision", form.get("subdivision"));
  addString(payload, "tower", form.get("tower"));
  return payload;
}

function getPurpose() {
  return document.querySelector("input[name='purpose']:checked").value;
}

function addNumber(payload, key, value) {
  if (value === null || value === "") return;
  const number = Number(value);
  if (Number.isFinite(number)) payload[key] = number;
}

function addString(payload, key, value) {
  const text = String(value || "").trim();
  if (text) payload[key] = text;
}

function applyExtracted(extracted) {
  setValueIfPresent("areaM2", extracted.area_m2);
  setValueIfPresent("bedrooms", extracted.bedrooms);
  setValueIfPresent("view", extracted.view);
  setValueIfPresent("furniture", extracted.furniture);

  if (extracted.purpose) {
    const purposeInput = document.querySelector(`input[name='purpose'][value='${extracted.purpose}']`);
    if (purposeInput) purposeInput.checked = true;
  }
  if (extracted.property_type && $("propertyType").querySelector(`option[value='${extracted.property_type}']`)) {
    $("propertyType").value = extracted.property_type;
  }
  if (extracted.project) {
    const matchingProject = state.projects.find((project) => {
      const aliases = [project.slug, project.name, ...(project.aliases || [])].map(normalizeText);
      return aliases.includes(normalizeText(extracted.project));
    });
    if (matchingProject) $("project").value = matchingProject.slug;
  }
}

function setValueIfPresent(id, value) {
  if (value === null || value === undefined || value === "") return;
  const input = $(id);
  if (!input) return;
  input.value = value;
}

function appendBotResponse(response) {
  appendMessage("bot", response.answer || "Đã xử lý xong.", {
    missingFields: response.missing_fields || [],
    intent: response.intent,
    extracted: response.extracted,
    pendingContext: state.pendingChatContext,
    conversationContext: state.conversationContext,
  });
}

function appendMessage(role, text, options = {}) {
  const entry = {
    role,
    text,
    missingFields: options.missingFields || [],
    intent: options.intent || null,
    extracted: options.extracted || null,
    pendingContext: options.pendingContext || null,
    conversationContext: options.conversationContext || null,
    timestamp: options.timestamp || new Date().toISOString(),
  };
  renderChatEntry(entry);
  if (options.save !== false) {
    state.chatHistory.push(entry);
    trimChatHistory();
    saveChatHistory();
  }
  updateChatHistoryMeta();
}

function renderChatEntry(entry) {
  const intro = $("chatLog").querySelector(".chat-intro");
  if (intro) intro.remove();

  const wrapper = document.createElement("article");
  wrapper.className = `message ${entry.role}`;
  const avatar = document.createElement("span");
  avatar.className = "avatar";
  avatar.textContent = entry.role === "user" ? "Bạn" : "AI";
  const content = document.createElement("div");
  content.className = "bubble";
  renderMessageContent(content, entry.text, entry.role);

  if (Array.isArray(entry.missingFields) && entry.missingFields.length) {
    const list = document.createElement("ul");
    list.className = "missing-list";
    entry.missingFields.forEach((field) => {
      const item = document.createElement("li");
      item.textContent = field;
      list.append(item);
    });
    content.append(list);
  }

  const meta = document.createElement("span");
  meta.className = "message-meta";
  meta.textContent = formatMessageTime(entry.timestamp);
  content.append(meta);

  wrapper.append(avatar, content);
  $("chatLog").append(wrapper);
  scrollChatToBottom();
}

function renderChatHistory() {
  const log = $("chatLog");
  log.textContent = "";
  if (!state.chatHistory.length) {
    renderChatIntro();
  } else {
    state.chatHistory.forEach((entry) => renderChatEntry(entry));
  }
  state.pendingChatContext = latestPendingContextFromHistory();
  state.conversationContext = latestConversationContextFromHistory();
  updateChatHistoryMeta();
}

function renderChatIntro() {
  const intro = document.createElement("div");
  intro.className = "chat-intro";
  const title = document.createElement("strong");
  title.textContent = "Bắt đầu với một câu hỏi";
  const body = document.createElement("span");
  body.textContent = "Chọn một mẫu hoặc nhập trực tiếp câu hỏi của bạn.";
  const chips = document.createElement("div");
  chips.className = "prompt-chips";
  [
    "Định giá bán căn hộ Vinhomes Smart City 54m2 2PN full nội thất",
    "Giá thuê hợp lý căn hộ Vinhomes Ocean Park 2PN",
    "Xu hướng giá Ocean Park căn hộ bán",
  ].forEach((prompt) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = prompt;
    button.addEventListener("click", () => {
      $("chatMessage").value = prompt;
      $("chatMessage").focus();
    });
    chips.append(button);
  });
  intro.append(title, body, chips);
  $("chatLog").append(intro);
}

function renderMessageContent(container, text, role) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (role === "bot" && lines.length && lines.every((line) => /^[-*•]\s+/.test(line))) {
    const list = document.createElement("ul");
    list.className = "response-list";
    lines.forEach((line) => {
      const item = document.createElement("li");
      item.textContent = line.replace(/^[-*•]\s+/, "");
      list.append(item);
    });
    container.append(list);
    return;
  }
  container.textContent = text;
}

function chatHistoryKey() {
  return state.auth?.user?.id ? `${CHAT_HISTORY_KEY}:user:${state.auth.user.id}` : CHAT_HISTORY_KEY;
}

function loadChatHistory() {
  try {
    const parsed = JSON.parse(localStorage.getItem(chatHistoryKey()) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((entry) => entry && ["user", "bot"].includes(entry.role) && typeof entry.text === "string")
      .map((entry) => ({
        role: entry.role,
        text: entry.text,
        missingFields: Array.isArray(entry.missingFields) ? entry.missingFields : [],
        intent: entry.intent || null,
        extracted: entry.extracted && typeof entry.extracted === "object" ? entry.extracted : null,
        pendingContext:
          entry.pendingContext && typeof entry.pendingContext === "object" ? entry.pendingContext : null,
        conversationContext:
          entry.conversationContext && typeof entry.conversationContext === "object" ? entry.conversationContext : null,
        timestamp: entry.timestamp || new Date().toISOString(),
      }))
      .slice(-MAX_CHAT_HISTORY);
  } catch {
    return [];
  }
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
  const missingFields = Array.isArray(response.missing_fields) ? response.missing_fields : [];
  if (!missingFields.length || !response.intent) {
    state.pendingChatContext = null;
    return;
  }
  state.pendingChatContext = {
    pending_intent: response.intent,
    missing_fields: missingFields,
    extracted: response.extracted || {},
  };
}

function latestConversationContextFromHistory() {
  for (let index = state.chatHistory.length - 1; index >= 0; index -= 1) {
    const entry = state.chatHistory[index];
    if (entry.conversationContext?.extracted) return entry.conversationContext;
  }
  return null;
}

function latestPendingContextFromHistory() {
  for (let index = state.chatHistory.length - 1; index >= 0; index -= 1) {
    const entry = state.chatHistory[index];
    if (entry.role === "user") return null;
    if (entry.pendingContext?.pending_intent) return entry.pendingContext;
  }
  return null;
}

function saveChatHistory() {
  try {
    localStorage.setItem(chatHistoryKey(), JSON.stringify(state.chatHistory));
  } catch {
    // Browser storage can be disabled or full; chat should still work for the current session.
  }
}

function trimChatHistory() {
  if (state.chatHistory.length > MAX_CHAT_HISTORY) {
    state.chatHistory = state.chatHistory.slice(-MAX_CHAT_HISTORY);
  }
}

function updateChatHistoryMeta() {
  const count = state.chatHistory.length;
  $("chatHistoryMeta").textContent = count
    ? `Đã lưu ${count} tin nhắn trên trình duyệt này.`
    : "Lịch sử chat được lưu trên trình duyệt này.";
}

function scrollChatToBottom() {
  const log = $("chatLog");
  log.scrollTop = log.scrollHeight;
}

function renderValuation(valuation, options = {}) {
  const purpose = valuation.purpose || getPurpose();
  const project = valuation.project || currentProjectName();
  const typeLabel = propertyTypeLabels[valuation.property_type] || valuation.property_type || "BĐS";
  $("resultMeta").textContent = `${purposeLabels[purpose] || purpose} - ${project} - ${typeLabel}. ${valuation.caveat || ""}`;
  $("p10Value").textContent = formatTotal(valuation.p10_total_vnd, purpose);
  $("p50Value").textContent = formatTotal(valuation.p50_total_vnd, purpose);
  $("p90Value").textContent = formatTotal(valuation.p90_total_vnd, purpose);
  const conf = valuation.confidence;
  const cv = $("confidenceValue");
  cv.textContent = confidenceLabels[conf] || conf || "-";
  cv.className = `confidence-badge ${conf ? 'conf-' + conf : ''}`;
  if ($("modelUsed")) $("modelUsed").textContent = valuation.model || "-";
  $("sampleValue").textContent = `${valuation.sample_size ?? 0} mẫu`;
  $("freshnessValue").textContent = formatDateTime(valuation.data_freshness);

  renderFactors(valuation.top_factors || [], valuation);
  renderComps(valuation.comparable_listings || [], purpose);
  if ((valuation.comparable_listings || []).length) {
    const firstComparable = valuation.comparable_listings[0];
    renderMapForComparable(firstComparable);
    if (options.amenityAdvice) {
      renderAmenities(options.amenityAdvice);
    } else {
      refreshAmenities(firstComparable);
    }
  } else {
    refreshAmenities();
  }
  drawValuationChart(valuation);
}

function summarizeValuation(valuation) {
  const purpose = valuation.purpose || getPurpose();
  const ppm = valuation.p50_price_per_m2_vnd
    ? `, tương đương ${formatPricePerM2(valuation.p50_price_per_m2_vnd)}`
    : "";
  return `Giá trung vị P50: ${formatTotal(valuation.p50_total_vnd, purpose)}${ppm}. Khoảng tham khảo P10-P90: ${formatTotal(
    valuation.p10_total_vnd,
    purpose,
  )} đến ${formatTotal(valuation.p90_total_vnd, purpose)}. P10 là vùng thấp, P90 là vùng cao của nhóm so sánh; mẫu unique: ${
    valuation.sample_size
  }.`;
}

function renderFactors(factors, valuation = {}) {
  const list = $("factorList");
  list.textContent = "";
  const items = [
    ...factors.map(readableFactor).filter(Boolean),
    ...factorCompletenessNotes(valuation),
  ];
  if (!items.length) {
    const item = document.createElement("li");
    item.textContent = "Chưa có yếu tố giải thích.";
    list.append(item);
    return;
  }
  items.forEach((factor) => {
    const item = document.createElement("li");
    item.textContent = factor;
    list.append(item);
  });
}

function readableFactor(factor) {
  const text = String(factor || "").trim();
  if (!text) return "";
  const key = normalizeText(text);
  if (key.includes("nguon hien tai la gia rao cong khai")) {
    return "Dữ liệu hiện tại chủ yếu là giá rao công khai; giá chốt thực tế có thể thấp hơn sau thương lượng.";
  }
  if (key.includes("bang gia tham khao") || key.includes("snapshot")) {
    return "Có thêm bảng giá tham khảo từ dự án/đại lý để đối chiếu, nhưng giá chính vẫn dựa trên các căn so sánh gần nhất.";
  }
  return text
    .replace(/\bmedian\b/gi, "mặt bằng chung")
    .replace(/P10-P90/gi, "khoảng thấp-cao")
    .replace(/listing/g, "tin rao")
    .replace(/comps/gi, "căn so sánh")
    .replace(/snapshot/gi, "bảng giá tham khảo")
    .replace(/verified transaction/gi, "giao dịch đã xác thực")
    .replace(/verified/gi, "đã xác thực")
    .replace(/sample size/gi, "số mẫu")
    .replace(/nhóm so sánh/gi, "nhóm căn tương tự")
    .replace(/giá\/m²/g, "đơn giá mỗi m²");
}

function factorCompletenessNotes(valuation = {}) {
  const missing = [];
  if (!fieldValue("view")) missing.push("hướng nhìn/view");
  if (!fieldValue("furniture")) missing.push("tình trạng nội thất");
  if (!fieldValue("subdivision")) missing.push("phân khu");
  const propertyType = valuation.property_type || $("propertyType")?.value;
  if (propertyType === "apartment" && !fieldValue("tower")) missing.push("mã tòa");
  if (!missing.length) return [];
  return [
    `Độ chính xác: chưa có ${joinVietnameseList(missing)} nên hệ thống đang dùng mặt bằng chung; bổ sung các thông tin này sẽ giúp khoảng giá sát hơn.`,
  ];
}

function renderComps(comps, purpose) {
  const tbody = $("compRows");
  tbody.textContent = "";
  if (!comps.length) {
    appendEmptyRow(tbody, 7, "Chưa có căn so sánh.");
    return;
  }

  comps.forEach((comp, index) => {
    const row = document.createElement("tr");
    row.dataset.compIndex = String(index);
    const prj = state.projects?.find(p => p.slug === comp.project);
    const projectName = prj ? prj.name : comp.project;
    
    row.append(
      textCell(cleanListingText(comp.title) || "Căn chưa có mô tả"),
      textCell(projectName || "-"),
      textCell(formatArea(comp.area_m2)),
      textCell(comp.bedrooms ?? "-"),
      textCell(formatComparablePrice(comp, purpose)),
      textCell(`${Math.round((comp.similarity_score || 0) * 100)}%`),
      mapCell(comp)
    );
    tbody.append(row);
  });
  refreshIcons();
}

async function refreshEvaluation() {
  try {
    const evaluation = await apiGet("/evaluation");
    state.latestEvaluation = evaluation;
    renderEvaluation(evaluation);
    drawMarketSummaryChart(evaluation);
  } catch (error) {
    renderEvaluationError(error.message);
  }
}

function renderEvaluation(evaluation) {
  const expected = evaluation.expected_sources?.length || 0;
  const observed = evaluation.observed_sources?.length || 0;
  $("rawRowsValue").textContent = formatInteger(evaluation.raw_listing_rows);
  $("uniqueRowsValue").textContent = formatInteger(evaluation.deduped_listing_rows);
  $("duplicateRowsValue").textContent = `${formatInteger(evaluation.duplicate_listing_rows)} (${formatPercent(
    evaluation.duplicate_rate,
  )})`;
  $("sourceCoverageValue").textContent = expected ? `${observed}/${expected}` : `${observed}`;
  $("dataMeta").textContent = `Cập nhật ${formatDateTime(evaluation.generated_at)}.`;

  const list = $("evaluationNotes");
  list.textContent = "";
  const notes = evaluation.notes?.length ? evaluation.notes : ["Chưa có ghi chú đánh giá dữ liệu."];
  notes.forEach((note) => {
    const item = document.createElement("li");
    item.textContent = note;
    list.append(item);
  });
}

function renderEvaluationError(message) {
  $("dataMeta").textContent = "Không tải được đánh giá dữ liệu.";
  $("rawRowsValue").textContent = "-";
  $("uniqueRowsValue").textContent = "-";
  $("duplicateRowsValue").textContent = "-";
  $("sourceCoverageValue").textContent = "-";
  const list = $("evaluationNotes");
  list.textContent = "";
  const item = document.createElement("li");
  item.textContent = message;
  list.append(item);
  drawMarketSummaryChart();
}

function mapCell(comp) {
  const cell = document.createElement("td");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "map-link-button";
  button.title = "Xem vị trí trên bản đồ";
  button.innerHTML = '<i data-lucide="map-pin"></i><span>Xem</span>';
  button.addEventListener("click", async () => {
    renderMapForComparable(comp);
    await refreshAmenities(comp);
  });
  cell.append(button);
  return cell;
}

function renderMapForComparable(comp) {
  state.activeComparable = comp;
  const parts = [
    cleanListingText(comp.address),
    cleanListingText(comp.subdivision),
    cleanListingText(comp.project),
    "Hà Nội",
  ].filter(Boolean);
  const label = cleanListingText(comp.title) || cleanListingText(comp.address) || comp.project || "Căn so sánh";
  renderMapForQuery(parts.join(", "), label);
}

function renderMapForQuery(query, label = query) {
  const safeQuery = String(query || "Vinhomes Hà Nội").trim() || "Vinhomes Hà Nội";
  const encoded = encodeURIComponent(safeQuery);
  $("mapFrame").src = `https://www.google.com/maps?q=${encoded}&output=embed`;
  $("openMapLink").href = `https://www.google.com/maps/search/?api=1&query=${encoded}`;
  $("mapMeta").textContent = label || safeQuery;
}

async function refreshAmenities(subject = state.activeComparable) {
  const project = $("project").value;
  if (!project) return;
  setPanelLoading("refreshAmenities", true);
  renderAmenitiesLoading(subject);
  try {
    const advice = await apiPost("/amenities/advice", amenityPayload(subject));
    renderAmenities(advice);
  } catch (error) {
    renderAmenitiesError(error.message);
  } finally {
    setPanelLoading("refreshAmenities", false);
  }
}

function amenityPayload(subject) {
  const payload = {
    project: $("project").value,
    purpose: getPurpose(),
    property_type: $("propertyType").value,
    max_places_per_category: 3,
  };
  addString(payload, "address", subject?.address);
  addString(payload, "subdivision", subject?.subdivision);
  addString(payload, "tower", subject?.tower);
  return payload;
}

function renderAmenities(advice) {
  state.latestAmenityAdvice = advice;
  $("amenitiesMeta").textContent = advice.location_label || advice.project || "Tiện ích quanh dự án";
  renderAmenityHighlights(advice);
  renderAmenityAdviceList(advice);
  renderAmenityCards(advice.categories || []);
  const firstCategory = (advice.categories || [])[0];
  if (firstCategory) renderMapForAmenity(firstCategory, advice.location_label);
}

function renderAmenityHighlights(advice) {
  const highlights = $("amenityHighlights");
  if (!highlights) return;
  highlights.textContent = "";
  const categories = advice.categories || [];
  const placesCount = categories.reduce((sum, category) => sum + (category.places?.length || 0), 0);
  const priorityLabels = amenityPriorityLabels(categories);
  const cards = [
    ["Khu vực", advice.location_label || advice.project || currentProjectName()],
    ["Nhóm tiện ích", categories.length ? `${categories.length} nhóm đang kiểm tra` : "Chưa có nhóm tiện ích"],
    ["Ưu tiên xem", priorityLabels || "Giao thông, siêu thị, y tế"],
  ];
  if (placesCount) cards[1][1] = `${placesCount} địa điểm trong ${categories.length} nhóm`;
  cards.forEach(([label, value]) => {
    const card = document.createElement("div");
    card.className = "amenity-highlight";
    const small = document.createElement("span");
    small.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value;
    card.append(small, strong);
    highlights.append(card);
  });
}

function renderAmenityAdviceList(advice) {
  const list = $("amenityAdviceList");
  list.textContent = "";
  const notes = amenitySummaryLines(advice);
  notes.forEach((note) => {
    const item = document.createElement("li");
    item.textContent = note;
    list.append(item);
  });
}

function renderAmenityCards(categories) {
  const grid = $("amenityCards");
  grid.textContent = "";
  if (!categories.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Chưa có tiện ích để hiển thị.";
    grid.append(empty);
    return;
  }

  categories.forEach((category) => {
    const card = document.createElement("article");
    card.className = "amenity-card";
    const title = document.createElement("div");
    title.className = "amenity-card-title";
    const heading = document.createElement("strong");
    heading.textContent = category.label;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "map-link-button";
    button.innerHTML = '<i data-lucide="map"></i><span>Map</span>';
    button.addEventListener("click", () => renderMapForAmenity(category));
    title.append(heading, button);

    const note = document.createElement("p");
    note.textContent = category.renter_note;
    const places = document.createElement("ul");
    places.className = "amenity-place-list";
    if (category.places?.length) {
      category.places.forEach((place) => {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = place.maps_url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = place.name;
        item.append(link);
        const meta = amenityPlaceMeta(place);
        if (meta) {
          const small = document.createElement("small");
          small.textContent = meta;
          item.append(small);
        }
        places.append(item);
      });
    } else {
      const item = document.createElement("li");
      item.textContent = "Mở Google Maps để xem kết quả thực tế.";
      places.append(item);
    }
    card.append(title, note, places);
    grid.append(card);
  });
  refreshIcons();
}

function renderMapForAmenity(category, locationLabel = "") {
  $("mapFrame").src = category.embed_url;
  $("openMapLink").href = category.map_url;
  $("mapMeta").textContent = `${category.label}${locationLabel ? ` - ${locationLabel}` : ""}`;
}

function renderAmenitiesPlaceholder(message) {
  state.latestAmenityAdvice = null;
  $("amenitiesMeta").textContent = message;
  renderAmenityEmptyHighlights(message);
  const list = $("amenityAdviceList");
  list.textContent = "";
  const item = document.createElement("li");
  item.textContent = message;
  list.append(item);
  const grid = $("amenityCards");
  grid.textContent = "";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = "Chưa có tiện ích để hiển thị.";
  grid.append(empty);
}

function renderAmenitiesError(message) {
  $("amenitiesMeta").textContent = "Không tải được tiện ích.";
  renderAmenityEmptyHighlights("Không tải được tiện ích.");
  const list = $("amenityAdviceList");
  list.textContent = "";
  const item = document.createElement("li");
  item.textContent = message;
  list.append(item);
  const grid = $("amenityCards");
  grid.textContent = "";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = "Chưa có tiện ích để hiển thị.";
  grid.append(empty);
}

function renderAmenitiesLoading(subject) {
  $("amenitiesMeta").textContent = subject?.title || subject?.address || currentProjectName();
  const highlights = $("amenityHighlights");
  if (highlights) {
    highlights.textContent = "";
    const loading = document.createElement("div");
    loading.className = "loading-state";
    loading.textContent = "Đang tải tiện ích quanh khu vực.";
    highlights.append(loading);
  }
  const list = $("amenityAdviceList");
  list.textContent = "";
  const item = document.createElement("li");
  item.textContent = "Đang tổng hợp các nhóm quan trọng trước.";
  list.append(item);
  const grid = $("amenityCards");
  grid.textContent = "";
  const loading = document.createElement("div");
  loading.className = "loading-state";
  loading.textContent = "Đang chuẩn bị chi tiết theo từng nhóm tiện ích.";
  grid.append(loading);
}

function renderAmenityEmptyHighlights(message) {
  const highlights = $("amenityHighlights");
  if (!highlights) return;
  highlights.textContent = "";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = message;
  highlights.append(empty);
}

function renderTrends(trends) {
  const chartArea = $("trendChartArea");
  const canvas = $("trendChart");
  const emptyState = $("trendEmptyState");
  
  if (!chartArea || !canvas || !emptyState) return;

  const windows = trends?.windows || {};
  const entries = Object.keys(trendLabels).map((key) => [trendLabels[key], windows[key]?.median]);
  const validEntries = entries.filter(([, val]) => val != null);

  if (validEntries.length === 0) {
    renderTrendError("Chưa có dữ liệu trend.");
    return;
  }
  
  canvas.style.display = "block";
  emptyState.style.display = "none";
  drawTrendChart(canvas, validEntries);
}

function renderTrendError(message) {
  const canvas = $("trendChart");
  const emptyState = $("trendEmptyState");
  if (canvas) canvas.style.display = "none";
  if (emptyState) {
    emptyState.style.display = "flex";
    emptyState.textContent = message;
  }
}

function drawTrendChart(canvas, dataPoints) {
  const container = canvas.parentElement;
  const rect = container.getBoundingClientRect();
  const width = Math.max(320, rect.width);
  const height = Math.max(200, rect.height);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  const padding = { top: 40, right: 40, bottom: 40, left: 60 };
  const graphWidth = width - padding.left - padding.right;
  const graphHeight = height - padding.top - padding.bottom;

  const values = dataPoints.map(([, val]) => val);
  const minVal = Math.min(...values) * 0.95;
  const maxVal = Math.max(...values) * 1.05;
  const range = maxVal - minVal || 1;

  // Draw axes
  ctx.beginPath();
  ctx.strokeStyle = "#e5e7eb";
  ctx.lineWidth = 1;
  ctx.moveTo(padding.left, padding.top);
  ctx.lineTo(padding.left, height - padding.bottom);
  ctx.lineTo(width - padding.right, height - padding.bottom);
  ctx.stroke();

  // Draw line
  ctx.beginPath();
  ctx.strokeStyle = "#006ee6";
  ctx.lineWidth = 3;
  ctx.lineJoin = "round";

  dataPoints.forEach(([label, val], i) => {
    const x = padding.left + (i / Math.max(1, dataPoints.length - 1)) * graphWidth;
    const y = height - padding.bottom - ((val - minVal) / range) * graphHeight;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Draw points and labels
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#006ee6";
  ctx.lineWidth = 2;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.font = "12px sans-serif";

  dataPoints.forEach(([label, val], i) => {
    const x = padding.left + (i / Math.max(1, dataPoints.length - 1)) * graphWidth;
    const y = height - padding.bottom - ((val - minVal) / range) * graphHeight;

    ctx.beginPath();
    ctx.arc(x, y, 4, 0, 2 * Math.PI);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#4b5563";
    ctx.fillText(label, x, height - padding.bottom + 8);
    
    ctx.fillStyle = "#111827";
    const purpose = getPurpose();
    const formattedVal = purpose === "rent" ? formatTotal(val, purpose) : formatPricePerM2(val);
    ctx.fillText(formattedVal, x, y - 20);
  });
}

function drawValuationChart(valuation) {
  const canvas = $("valuationChart");
  if (!canvas) return;
  const container = canvas.parentElement;
  const rect = container.getBoundingClientRect();
  const width = Math.max(320, rect.width);
  const height = Math.max(200, rect.height);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  const values = valuation
    ? [valuation.p10_total_vnd, valuation.p50_total_vnd, valuation.p90_total_vnd].map(Number)
    : [];
  if (!values.length || values.some((value) => !Number.isFinite(value))) {
    drawEmptyChart(ctx, width, height);
    return;
  }

  const [p10, p50, p90] = values;
  const left = 42;
  const right = width - 24;
  const bottom = height - 42;
  const top = 28;
  const range = Math.max(p90 - p10, 1);
  const min = p10 - range * 0.45;
  const max = p90 + range * 0.45;
  const toX = (value) => left + ((value - min) / (max - min)) * (right - left);

  ctx.strokeStyle = "#dce3df";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(left, bottom);
  ctx.lineTo(right, bottom);
  ctx.stroke();

  ctx.beginPath();
  const sigma = Math.max((p90 - p10) / 2.56, range / 4);
  const amplitude = bottom - top - 22;
  for (let i = 0; i <= 120; i += 1) {
    const x = left + ((right - left) * i) / 120;
    const value = min + ((max - min) * i) / 120;
    const z = (value - p50) / sigma;
    const y = bottom - Math.exp(-0.5 * z * z) * amplitude;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = "#0d7f73";
  ctx.lineWidth = 3;
  ctx.stroke();

  drawMarker(ctx, toX(p10), bottom, "P10", formatTotal(p10, valuation.purpose));
  drawMarker(ctx, toX(p50), bottom, "P50", formatTotal(p50, valuation.purpose), true);
  drawMarker(ctx, toX(p90), bottom, "P90", formatTotal(p90, valuation.purpose));
}

function drawEmptyChart(ctx, width, height) {
  ctx.strokeStyle = "#dce3df";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(36, height - 42);
  ctx.lineTo(width - 24, height - 42);
  ctx.stroke();
  ctx.fillStyle = "#65716b";
  ctx.font = "14px sans-serif";
  ctx.fillText("Khoảng P10-P50-P90 sẽ hiện ở đây sau khi định giá.", 36, 72);
}

function drawMarker(ctx, x, bottom, label, value, isMain = false) {
  ctx.strokeStyle = isMain ? "#c95f44" : "#a67823";
  ctx.fillStyle = ctx.strokeStyle;
  ctx.lineWidth = isMain ? 2 : 1;
  ctx.beginPath();
  ctx.moveTo(x, 28);
  ctx.lineTo(x, bottom + 4);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(x, bottom, isMain ? 5 : 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.font = isMain ? "700 12px sans-serif" : "12px sans-serif";
  ctx.fillText(label, x - 12, bottom + 22);
  ctx.font = "11px sans-serif";
  ctx.fillStyle = "#65716b";
  ctx.fillText(value, Math.max(8, Math.min(x - 34, ctx.canvas.width - 150)), bottom + 36);
}

function drawMarketSummaryChart(evaluation = state.latestEvaluation) {
  const canvas = $("summaryChart");
  if (!canvas) return;
  const container = canvas.parentElement;
  const rect = container.getBoundingClientRect();
  const width = Math.max(320, rect.width);
  const height = Math.max(240, rect.height);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  const rows = (evaluation?.chart?.by_project || []).slice(0, 6);
  if (!rows.length) {
    ctx.fillStyle = "#68717f";
    ctx.font = "14px sans-serif";
    ctx.fillText("Chưa có dữ liệu để vẽ tổng hợp.", 24, 56);
    return;
  }

  const left = 38;
  const right = width - 22;
  const top = 26;
  const bottom = height - 76;
  const max = Math.max(...rows.map((row) => Number(row.value) || 0), 1);
  const gap = 12;
  const barWidth = Math.max(28, (right - left - gap * (rows.length - 1)) / rows.length);

  ctx.strokeStyle = "#dce2eb";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(left, bottom);
  ctx.lineTo(right, bottom);
  ctx.stroke();

  rows.forEach((row, index) => {
    const value = Number(row.value) || 0;
    const barHeight = ((bottom - top) * value) / max;
    const x = left + index * (barWidth + gap);
    const y = bottom - barHeight;

    ctx.fillStyle = index % 2 ? "#4e7484" : "#3f65aa";
    roundRect(ctx, x, y, barWidth, barHeight, 6);
    ctx.fill();

    ctx.fillStyle = "#202634";
    ctx.font = "700 12px sans-serif";
    ctx.fillText(formatInteger(value), x + 4, Math.max(top + 14, y - 8));

    ctx.fillStyle = "#68717f";
    ctx.font = "11px sans-serif";
    wrapCanvasText(ctx, projectChartLabel(row.label), x, bottom + 18, barWidth + 14, 12, 3);
  });
}

function roundRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function wrapCanvasText(ctx, text, x, y, maxWidth, lineHeight, maxLines) {
  const words = String(text || "").split(/\s+/);
  let line = "";
  let lines = 0;
  words.forEach((word) => {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line && lines < maxLines - 1) {
      ctx.fillText(line, x, y + lines * lineHeight);
      line = word;
      lines += 1;
    } else {
      line = test;
    }
  });
  if (line && lines < maxLines) ctx.fillText(line, x, y + lines * lineHeight);
}

function projectChartLabel(value) {
  return String(value || "Dự án").replace(/\s+/g, " ").trim();
}

async function apiGet(path) {
  return request(path);
}

async function apiPost(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function request(path, options = {}) {
  const url = `${state.apiBase}${path}`;
  const headers = new Headers(options.headers || {});
  if (state.auth?.token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${state.auth.token}`);
  }
  const response = await fetch(url, { ...options, headers });
  let payload = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail = payload?.detail || payload || response.statusText;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg || item).join(", ") : detail);
  }
  return payload;
}

function setApiStatus(kind, text) {
  const status = $("apiStatus");
  status.className = `status-pill status-${kind}`;
  status.textContent = text;
}

function setPanelLoading(id, loading) {
  const element = $(id);
  if (!element) return;
  element.classList.toggle("is-loading", loading);
  if ("disabled" in element) element.disabled = loading;
}

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function currentProjectName() {
  const option = $("project").selectedOptions[0];
  return option ? option.textContent : "-";
}

function normalizeText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function fieldValue(id) {
  return String($(id)?.value || "").trim();
}

function joinVietnameseList(items) {
  const values = items.filter(Boolean);
  if (values.length <= 1) return values[0] || "";
  if (values.length === 2) return `${values[0]} và ${values[1]}`;
  return `${values.slice(0, -1).join(", ")} và ${values.at(-1)}`;
}

function cleanListingText(value) {
  return String(value || "")
    .replace(/\]\(https?:\/\/[^)]+\)/gi, "")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/\s+Đăng\s+.*$/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

function textCell(value) {
  const cell = document.createElement("td");
  cell.textContent = value === null || value === undefined || value === "" ? "-" : value;
  return cell;
}

function textCellWithLink(text, href) {
  const cell = document.createElement("td");
  if (href) {
    const link = document.createElement("a");
    link.href = href;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = text;
    cell.append(link);
  } else {
    cell.textContent = text;
  }
  return cell;
}

function appendEmptyRow(tbody, colspan, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = colspan;
  cell.textContent = message;
  row.append(cell);
  tbody.append(row);
}

function formatTotal(value, purpose = "sale") {
  if (!Number.isFinite(Number(value))) return "-";
  return purpose === "rent" ? `${formatCompactVnd(value)} / tháng` : formatCompactVnd(value);
}

function formatTrendMetric(value, purpose = "sale") {
  if (!Number.isFinite(Number(value))) return "-";
  return purpose === "rent" ? `${formatCompactVnd(value)} / tháng` : formatPricePerM2(value);
}

function formatComparablePrice(comp, purpose = "sale") {
  if (purpose === "rent") return formatTotal(comp.rent_monthly_vnd, "rent");
  const total = formatTotal(comp.price_total_vnd, "sale");
  const ppm = comp.price_per_m2_vnd ? ` (${formatPricePerM2(comp.price_per_m2_vnd)})` : "";
  return `${total}${ppm}`;
}

function amenityPlaceMeta(place) {
  const parts = [];
  if (Number.isFinite(Number(place.distance_m))) parts.push(`${formatInteger(place.distance_m)} m`);
  if (Number.isFinite(Number(place.rating))) parts.push(`${formatNumber(place.rating)} sao`);
  if (Number.isFinite(Number(place.user_ratings_total))) parts.push(`${formatInteger(place.user_ratings_total)} đánh giá`);
  if (place.address) parts.push(place.address);
  return parts.join(" - ");
}

function amenityPriorityLabels(categories = []) {
  const preferred = ["commute", "grocery", "health", "school", "green"];
  const ordered = [...categories].sort((a, b) => preferred.indexOf(a.key) - preferred.indexOf(b.key));
  return ordered
    .filter((category) => preferred.includes(category.key))
    .slice(0, 3)
    .map((category) => category.label)
    .join(", ");
}

function amenitySummaryLines(advice) {
  const categories = advice.categories || [];
  const priority = amenityPriorityLabels(categories);
  const lines = [
    priority ? `Nên xem trước: ${priority}.` : "Nên xem trước giao thông, siêu thị và y tế.",
  ];
  const withPlaces = categories.filter((category) => category.places?.length);
  if (withPlaces.length) {
    lines.push(`${withPlaces.length}/${categories.length} nhóm đang có địa điểm cụ thể để mở nhanh trên bản đồ.`);
  } else if (categories.length) {
    lines.push("Có thể mở từng nhóm bên dưới để xem kết quả bản đồ theo đúng khu vực.");
  }
  const usefulNotes = [
    ...splitBulletLines(advice.llm_advice),
    ...(Array.isArray(advice.advisory_notes) ? advice.advisory_notes : []),
  ].filter((line) => line && !isTechnicalAmenityLine(line));
  usefulNotes.slice(0, 2).forEach((line) => {
    if (!lines.includes(line)) lines.push(line);
  });
  return lines.slice(0, 4);
}

function isTechnicalAmenityLine(line) {
  const key = normalizeText(line);
  return [
    "serpapi",
    "google places",
    "provider",
    "fallback",
    "api",
    "loi tim kiem",
    "request_denied",
  ].some((term) => key.includes(term));
}

function splitBulletLines(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.replace(/^[-*•]\s+/, "").trim())
    .filter(Boolean);
}

function formatArea(value) {
  return Number.isFinite(Number(value)) ? `${formatNumber(value)} m²` : "-";
}

function formatPricePerM2(value) {
  if (!Number.isFinite(Number(value))) return "-";
  return `${formatNumber(Number(value) / 1_000_000)} tr/m²`;
}

function formatCompactVnd(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  if (Math.abs(number) >= 1_000_000_000) return `${formatNumber(number / 1_000_000_000)} tỷ`;
  if (Math.abs(number) >= 1_000_000) return `${formatNumber(number / 1_000_000)} triệu`;
  return `${new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(number)} đ`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("vi-VN", {
    maximumFractionDigits: 1,
  }).format(Number(value));
}

function formatInteger(value) {
  return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(Number(value) || 0);
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${formatNumber(number * 100)}%`;
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

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function formatMessageTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  }).format(date);
}

window.addEventListener("resize", () => {
  drawValuationChart(state.latestValuation);
  drawMarketSummaryChart(state.latestEvaluation);
});

async function refreshNews(project = $("project")?.value) {
  const grid = $("newsGrid");
  if (!grid) return;
  const selectedProject = project || currentProjectName();
  renderNewsLoading();
  try {
    const payload = await apiGet(`/news?${new URLSearchParams({ project: selectedProject, limit: "5" }).toString()}`);
    state.latestNews = payload;
    renderNews(payload);
  } catch (error) {
    state.latestNews = null;
    renderNewsError(error.message);
  }
}

function renderNews(payload) {
  const grid = $("newsGrid");
  if (!grid) return;
  const items = payload?.items || [];
  $("newsMeta").textContent = payload?.project ? `Tin liên quan đến ${payload.project}.` : "Tin liên quan đến dự án.";
  grid.textContent = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Chưa có tin phù hợp.";
    grid.append(empty);
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "news-card";
    const title = document.createElement("h3");
    const link = document.createElement("a");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = item.title || "Tin liên quan";
    title.append(link);
    const snippet = document.createElement("p");
    snippet.textContent = item.snippet || "Mở nguồn tin để xem chi tiết.";
    const meta = document.createElement("div");
    meta.className = "news-meta";
    meta.textContent = newsMetaText(item) || "Tin mới";
    card.append(title, snippet, meta);
    grid.append(card);
  });
}

function renderNewsLoading() {
  $("newsMeta").textContent = "Đang tải tin liên quan đến dự án.";
  const grid = $("newsGrid");
  grid.textContent = "";
  const loading = document.createElement("div");
  loading.className = "loading-state";
  loading.textContent = "Đang tải tin tức mới nhất.";
  grid.append(loading);
}

function renderNewsError(message) {
  $("newsMeta").textContent = "Không tải được tin tức.";
  const grid = $("newsGrid");
  grid.textContent = "";
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = message;
  grid.append(empty);
}

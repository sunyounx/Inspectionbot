/**
 * Precision Curator SPA — inspect / history / terms / admin
 */

const VIEWS = ["inspect", "copywriter", "history", "terms", "manual", "admin"];
const VIEW_TITLES = {
  inspect: "소재 검수",
  copywriter: "카피 창작",
  history: "히스토리 탐색",
  terms: "용어 해석",
  manual: "수동 히스토리 적재",
  admin: "슬랙 승인 대기",
};

// —— DOM ——
const viewTitle = document.getElementById("viewTitle");
const contextTitle = document.getElementById("contextTitle");
const contextBody = document.getElementById("contextBody");
const btnNewInspection = document.getElementById("btnNewInspection");

const chatLog = document.getElementById("chatLog");
const textInput = document.getElementById("textInput");
const imageInput = document.getElementById("imageInput");
const imagePreview = document.getElementById("imagePreview");
const sendBtn = document.getElementById("sendBtn");

const gdriveComposerStatus = document.getElementById("gdriveComposerStatus");

const historyList = document.getElementById("historyList");
const historyFilters = document.getElementById("historyFilters");
const historyRefreshBtn = document.getElementById("historyRefreshBtn");
const historyChatLog = document.getElementById("historyChatLog");
const historyQueryInput = document.getElementById("historyQueryInput");
const historyQueryBtn = document.getElementById("historyQueryBtn");

const termsChatLog = document.getElementById("termsChatLog");
const termsInput = document.getElementById("termsInput");
const termsSendBtn = document.getElementById("termsSendBtn");

const copywriterChatLog = document.getElementById("copywriterChatLog");
const copywriterInput = document.getElementById("copywriterInput");
const copywriterSendBtn = document.getElementById("copywriterSendBtn");

/** 카피 조건 (뷰 전환 시에도 유지 — 모듈 스코프 단일 객체) */
const copyConditions = {
  medium: "DA 이미지",
  tone: "기본",
  maxChars: 0,
  copyType: "전체",
  extra: "",
};

function setCopyConditionField(field, value) {
  if (field === "maxChars") {
    copyConditions.maxChars = parseInt(value, 10) || 0;
  } else if (field === "medium") {
    copyConditions.medium = value;
  } else if (field === "tone") {
    copyConditions.tone = value;
  } else if (field === "copyType") {
    copyConditions.copyType = value;
  }
}

function applyCopyChipSelect(groupEl, chipEl) {
  const field = groupEl.dataset.field;
  const value = chipEl.dataset.value;
  if (!field || value === undefined) return;
  groupEl.querySelectorAll(".copy-chip").forEach((c) => c.classList.remove("active"));
  chipEl.classList.add("active");
  setCopyConditionField(field, value);
}

/** 인터랙티브 버블에서 「이 조건으로 생성」 시 — 기본값만이어도 🎯 블록을 항상 보냄 (재질문 루프 방지) */
function buildConditionPrefixExplicit() {
  const mc =
    copyConditions.maxChars > 0 ? `${copyConditions.maxChars}자 이내` : "제한없음";
  const parts = [
    `[매체] ${copyConditions.medium}`,
    `[톤] ${copyConditions.tone}`,
    `[글자수] ${mc}`,
    `[카피유형] ${copyConditions.copyType}`,
  ];
  if (copyConditions.extra.trim()) parts.push(`[추가조건] ${copyConditions.extra.trim()}`);
  return `🎯 조건: ${parts.join(" / ")}\n\n`;
}

/** Gemini 파싱 없이 휴리스틱: 조건 질문 응답이면 인터랙티브 버블로 대체 */
function looksLikeCopywriterConditionQuestion(text) {
  if (!text || typeof text !== "string") return false;
  return text.includes("매체") && text.includes("톤") && text.includes("글자수");
}

function initCopywriterPickerChips() {
  if (copywriterChatLog && !copywriterChatLog.__copywriterPickerChipBound) {
    copywriterChatLog.__copywriterPickerChipBound = true;
    copywriterChatLog.addEventListener("click", (e) => {
      const chip = e.target.closest(".copy-chip");
      if (!chip) return;
      const pickerBubble = chip.closest(".copywriter-picker-bubble");
      if (!pickerBubble || !copywriterChatLog.contains(pickerBubble)) return;
      const group = chip.closest(".copy-chip-group");
      if (!group) return;
      applyCopyChipSelect(group, chip);
    });
  }
}

initCopywriterPickerChips();

async function handleCopywriterInspectResult(res, logEl, originalMessage) {
  removeLastBubble(logEl);
  if (!res.ok) {
    const text = await res.text();
    addBubble(logEl, "bot", `요청 실패 (${res.status})\n${text}`);
    return;
  }
  const data = await res.json();
  if (looksLikeCopywriterConditionQuestion(data.feedback || "")) {
    addConditionPickerBubble(logEl, originalMessage, data.rules_checked);
  } else {
    addBubble(logEl, "bot", formatBotMessage(data.feedback), `copybank: ${data.rules_checked}건`, {
      asHtml: true,
    });
  }
}

/**
 * 클릭 가능한 칩 + 추가 조건 + 생성 버튼 (카피 창작 전용, Gemini 선호출 없음)
 * @param {string} originalMessage — 사용자가 입력창에 쓴 본문
 */
function addConditionPickerBubble(logEl, originalMessage, rulesChecked) {
  const wrap = el("div", { className: "msg-row bot" });
  const bubble = el("div", { className: "bubble bot copywriter-picker-bubble" });

  const mediumGroup = el("div", { className: "copy-chip-group copy-picker-section", "data-field": "medium" });
  mediumGroup.appendChild(el("div", { className: "copy-picker-section-title", text: "📺 매체" }));
  const mediumChips = el("div", { className: "copy-chips" });
  const mediumOpts = [
    ["DA 이미지", "DA 이미지"],
    ["인스타 릴스", "릴스"],
    ["카드뉴스", "카드뉴스"],
    ["상세페이지", "상세페이지"],
    ["블로그", "블로그"],
  ];
  mediumOpts.forEach(([val, label]) => {
    const active = copyConditions.medium === val;
    mediumChips.appendChild(
      el("button", {
        type: "button",
        className: "copy-chip" + (active ? " active" : ""),
        "data-value": val,
        text: `[${label}]`,
      })
    );
  });
  mediumGroup.appendChild(mediumChips);
  bubble.appendChild(mediumGroup);

  const toneGroup = el("div", { className: "copy-chip-group copy-picker-section", "data-field": "tone" });
  toneGroup.appendChild(el("div", { className: "copy-picker-section-title", text: "🎵 톤" }));
  const toneChips = el("div", { className: "copy-chips" });
  const toneOpts = [
    ["기본", "기본"],
    ["부드럽게", "부드럽게"],
    ["후킹 강하게", "후킹"],
    ["유머", "유머"],
    ["고급스럽게", "고급"],
  ];
  toneOpts.forEach(([val, label]) => {
    const active = copyConditions.tone === val;
    toneChips.appendChild(
      el("button", {
        type: "button",
        className: "copy-chip" + (active ? " active" : ""),
        "data-value": val,
        text: `[${label}]`,
      })
    );
  });
  toneGroup.appendChild(toneChips);
  bubble.appendChild(toneGroup);

  const charGroup = el("div", { className: "copy-chip-group copy-picker-section", "data-field": "maxChars" });
  charGroup.appendChild(el("div", { className: "copy-picker-section-title", text: "📏 글자수" }));
  const charChips = el("div", { className: "copy-chips" });
  const charOpts = [
    ["0", "제한없음"],
    ["15", "15자"],
    ["20", "20자"],
    ["30", "30자"],
    ["50", "50자"],
  ];
  charOpts.forEach(([val, label]) => {
    const active = String(copyConditions.maxChars) === val;
    charChips.appendChild(
      el("button", {
        type: "button",
        className: "copy-chip" + (active ? " active" : ""),
        "data-value": val,
        text: `[${label}]`,
      })
    );
  });
  charGroup.appendChild(charChips);
  bubble.appendChild(charGroup);

  const typeGroup = el("div", { className: "copy-chip-group copy-picker-section", "data-field": "copyType" });
  typeGroup.appendChild(el("div", { className: "copy-picker-section-title", text: "📝 유형" }));
  const typeChips = el("div", { className: "copy-chips" });
  const typeOpts = ["전체", "훅만", "CTA만", "설득만"];
  typeOpts.forEach((label) => {
    const active = copyConditions.copyType === label;
    typeChips.appendChild(
      el("button", {
        type: "button",
        className: "copy-chip" + (active ? " active" : ""),
        "data-value": label,
        text: `[${label}]`,
      })
    );
  });
  typeGroup.appendChild(typeChips);
  bubble.appendChild(typeGroup);

  const extraWrap = el("div", { className: "copy-picker-extra copy-extra-input" });
  extraWrap.appendChild(el("label", { className: "copy-picker-extra-label", text: "추가 조건" }));
  const extraField = el("input", {
    type: "text",
    className: "copy-picker-extra-field",
    placeholder: "예: 프로틴 강조, 여름 시즌…",
    value: copyConditions.extra || "",
  });
  extraField.addEventListener("input", () => {
    copyConditions.extra = extraField.value || "";
  });
  extraWrap.appendChild(extraField);
  bubble.appendChild(extraWrap);

  const confirmBtn = el("button", {
    type: "button",
    className: "btn btn-primary copywriter-picker-confirm",
    text: "✅ 이 조건으로 생성",
  });
  bubble.appendChild(confirmBtn);

  wrap.appendChild(bubble);
  const meta =
    rulesChecked !== undefined && rulesChecked !== null
      ? `copybank: ${rulesChecked}건 · 조건 선택`
      : "조건 선택";
  wrap.appendChild(el("div", { className: "msg-meta", text: meta }));

  logEl.appendChild(wrap);
  logEl.scrollTop = logEl.scrollHeight;

  confirmBtn.addEventListener("click", async () => {
    if (confirmBtn.disabled) return;
    // originalMessage가 비어 있으면(탭 진입 시 디폴트 picker) 입력창 값을 그때 읽는다.
    const liveInput = (copywriterInput?.value || "").trim();
    const userMessage = (originalMessage && originalMessage.trim()) || liveInput;
    if (!userMessage) {
      addBubble(logEl, "bot", "카피 요청을 입력창에 적고 다시 [생성]을 눌러주세요.");
      return;
    }
    confirmBtn.disabled = true;
    copyConditions.extra = extraField.value || "";
    const prefix = buildConditionPrefixExplicit();
    const fullMessage = prefix + userMessage;
    if (!originalMessage || !originalMessage.trim()) {
      // 디폴트 picker 경로: 사용자가 아직 user 버블을 띄운 적 없으니 여기서 띄우고 입력창을 비운다.
      addBubble(logEl, "user", userMessage);
      if (copywriterInput) copywriterInput.value = "";
    } else {
      addBubble(logEl, "user", userMessage);
    }
    addBubble(logEl, "bot", "카피를 생성 중입니다...", "잠시만 기다려주세요");
    try {
      const res = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: fullMessage,
          mode: "카피창작",
        }),
      });
      await handleCopywriterInspectResult(res, logEl, userMessage);
    } catch (e) {
      removeLastBubble(logEl);
      addBubble(logEl, "bot", `에러: ${e}`);
    } finally {
      confirmBtn.disabled = false;
    }
  });
}

function ensureCopywriterDefaultPicker() {
  if (!copywriterChatLog) return;
  // 이미 메시지/피커가 떠 있으면 중복 표시하지 않음
  if (copywriterChatLog.children.length > 0) return;
  addConditionPickerBubble(copywriterChatLog, "");
}

const adminCardsSlack = document.getElementById("adminCardsSlack");
const adminCardsFigma = document.getElementById("adminCardsFigma");
const adminCountSlack = document.getElementById("adminCountSlack");
const adminCountFigma = document.getElementById("adminCountFigma");

function isFigmaPending(item) {
  return ((item && item.source_ts) || "").startsWith("figma:");
}

function renderAdminColumns(items) {
  if (adminCardsSlack) adminCardsSlack.innerHTML = "";
  if (adminCardsFigma) adminCardsFigma.innerHTML = "";

  const slackItems = items.filter((x) => !isFigmaPending(x));
  const figmaItems = items.filter(isFigmaPending);

  if (adminCountSlack) adminCountSlack.textContent = String(slackItems.length);
  if (adminCountFigma) adminCountFigma.textContent = String(figmaItems.length);

  if (adminCardsSlack) {
    if (!slackItems.length) {
      adminCardsSlack.appendChild(el("div", { className: "history-card", text: "대기중인 Slack 항목이 없습니다." }));
    } else {
      slackItems.forEach((item) => adminCardsSlack.appendChild(renderAdminCard(item)));
    }
  }

  if (adminCardsFigma) {
    if (!figmaItems.length) {
      adminCardsFigma.appendChild(el("div", { className: "history-card", text: "대기중인 Figma 항목이 없습니다." }));
    } else {
      figmaItems.forEach((item) => adminCardsFigma.appendChild(renderAdminCard(item)));
    }
  }
}

function appendAdminColumns(items) {
  const slackItems = items.filter((x) => !isFigmaPending(x));
  const figmaItems = items.filter(isFigmaPending);

  if (adminCardsSlack && slackItems.length) {
    slackItems.forEach((item) => adminCardsSlack.appendChild(renderAdminCard(item)));
  }
  if (adminCardsFigma && figmaItems.length) {
    figmaItems.forEach((item) => adminCardsFigma.appendChild(renderAdminCard(item)));
  }

  if (adminCountSlack) {
    const total = adminListCache.filter((x) => !isFigmaPending(x)).length;
    adminCountSlack.textContent = String(total);
  }
  if (adminCountFigma) {
    const total = adminListCache.filter(isFigmaPending).length;
    adminCountFigma.textContent = String(total);
  }
}
const adminStatus = document.getElementById("adminStatus");
const adminRefreshBtn = document.getElementById("adminRefreshBtn");
const adminSearchInput = document.getElementById("adminSearch");
const adminAuthorInput = document.getElementById("adminAuthor");
const adminStatusFilters = document.getElementById("adminStatusFilters");
const adminOrderSelect = document.getElementById("adminOrder");
const adminLoadMoreBtn = document.getElementById("adminLoadMoreBtn");

const manualTextEl = document.getElementById("manualText");
const manualAuthorEl = document.getElementById("manualAuthor");
const manualCategoryEl = document.getElementById("manualCategory");
const manualSubmitBtn = document.getElementById("manualSubmitBtn");
const manualGoHistoryBtn = document.getElementById("manualGoHistoryBtn");
const manualStatusEl = document.getElementById("manualStatus");

const historyModal = document.getElementById("historyModal");
const historyModalTitle = document.getElementById("historyModalTitle");
const historyModalBadge = document.getElementById("historyModalBadge");
const historyModalBody = document.getElementById("historyModalBody");
const historyModalClose = document.getElementById("historyModalClose");
const historyModalCard = historyModal?.querySelector(".modal-card");
const historyModalMeta = document.getElementById("historyModalMeta");
const historyModalEdit = document.getElementById("historyModalEdit");
const historyModalDelete = document.getElementById("historyModalDelete");
const historyModalSave = document.getElementById("historyModalSave");
const historyModalCancel = document.getElementById("historyModalCancel");
const historyModalActionsRead = document.getElementById("historyModalActionsRead");
const historyModalActionsEdit = document.getElementById("historyModalActionsEdit");

const adminModal = document.getElementById("adminModal");
const adminModalTitle = document.getElementById("adminModalTitle");
const adminModalBody = document.getElementById("adminModalBody");
const adminModalClose = document.getElementById("adminModalClose");
const adminModalMeta = document.getElementById("adminModalMeta");
const adminModalActions = document.getElementById("adminModalActions");
const adminModalConflict = document.getElementById("adminModalConflict");
const adminModalCard = adminModal?.querySelector(".modal-card");

const lightbox = document.getElementById("lightbox");
const lightboxImg = document.getElementById("lightboxImg");
const lightboxClose = document.getElementById("lightboxClose");

const HISTORY_SCOPE_OPTIONS = ["영상", "이미지DA", "카피", "전체"];
const HISTORY_TYPE_OPTIONS = ["방향성", "규칙"];
const HISTORY_CATEGORY_OPTIONS = ["크리에이티브", "프로모션", "CRM", "브랜딩", "퍼포먼스", "기타", "미분류"];

const appRoot = document.querySelector(".app");
const historyChatStats = document.getElementById("historyChatStats");
const rawMessageList = document.getElementById("rawMessageList");
const historyChatPanel = document.getElementById("historyChatPanel");
const historyChatLabel = document.getElementById("historyChatLabel");
const rawFilters = document.getElementById("rawFilters");
const rawFiltersExtra = document.getElementById("rawFiltersExtra");
const rawSearchInput = document.getElementById("rawSearch");
const rawAuthorInput = document.getElementById("rawAuthor");
const rawHasFilesInput = document.getElementById("rawHasFiles");
const rawOrderSelect = document.getElementById("rawOrder");
const historyCategoryToolbar = document.getElementById("historyCategoryToolbar");
const historyCategoryTabs = document.getElementById("historyCategoryTabs");

// —— State ——
let currentView = "inspect";
/** 소재 검수 첨부 [{ base64?, mediaType, dataUrl, file, name, size, isVideo? }] — 전송은 항상 file 원본(FormData /inspect-upload). base64·dataUrl은 미리보기·버블용 */
let inspectImageList = [];
const MAX_INSPECT_IMAGES = 8;
/** 로컬 첨부 업로드 상한 (바이트). 영상은 서버에서 압축합니다. */
const MAX_INSPECT_UPLOAD_BYTES = 500 * 1024 * 1024;

let lastInspectResult = null;

/** Full history list (GET /api/history, no filter) — used for stats + detail lookup */
let historyRecordsAll = [];
let historyFilterStatus = "";
let historyCategoryFilter = "";
let selectedHistoryId = null;

let historySubTab = "history";
let rawFilterKind = "";
let rawSearchQuery = "";
let rawAuthor = "";
let rawHasFiles = false;
let rawOrder = "desc";
let rawMessagesCache = [];
/** parent_ts → 스레드 댓글 목록 캐시 */
let rawThreadCache = {};

const recentTerms = [];
const MAX_RECENT_TERMS = 12;

const ADMIN_LIMIT = 100;
let adminListCache = [];
let adminSearch = "";
let adminAuthor = "";
/** "" 이면 대기중+처리중 전체 */
let adminStatusFilter = "대기중";
let adminOrder = "desc";
let adminOffset = 0;
let adminTotal = 0;
let adminHasMore = false;
let adminPollTimer = null;

let historyModalCurrentItem = null;
let isEditingHistory = false;

let adminModalCurrentItem = null;

let gdriveLoggedIn = false;

function revokeInspectBlobUrl(item) {
  if (!item) return;
  const u = item.dataUrl;
  if (typeof u === "string" && u.startsWith("blob:")) {
    try {
      URL.revokeObjectURL(u);
    } catch (_) {
      /* ignore */
    }
  }
}

function clearLocalInspectImages() {
  inspectImageList.forEach(revokeInspectBlobUrl);
  inspectImageList = [];
  if (imageInput) imageInput.value = "";
}

/** 텍스트 안의 Google Drive 폴더 URL(또는 전체가 folder id인 경우)에서 folder id 추출 */
function parseDriveFolderId(text) {
  const s = String(text || "");
  if (!s.trim()) return null;
  const m = s.match(/drive\.google\.com\/drive\/(?:u\/\d+\/)?folders\/([a-zA-Z0-9_-]+)/);
  if (m?.[1]) return m[1];
  const t = s.trim();
  if (/^[a-zA-Z0-9_-]{10,}$/.test(t) && !/[/?]/.test(t)) return t;
  return null;
}

/** Figma design/file/board URL에서 file key · node-id 추출 (node-id는 API용 콜론 형식으로 통일) */
function parseFigmaUrl(text) {
  const s = String(text || "");
  const m = s.match(/figma\.com\/(?:design|file|board)\/([a-zA-Z0-9]{22,128})/);
  if (!m) return null;
  const nodeMatch = s.match(/[?&]node-id=([^&]+)/);
  let nodeId = nodeMatch ? decodeURIComponent(nodeMatch[1].replace(/\+/g, " ")) : null;
  if (nodeId) nodeId = nodeId.replace(/-/g, ":");
  return { fileKey: m[1], nodeId: nodeId || null };
}

function addTeamsSendBar(logEl, inspection) {
  const id = inspection?.id;
  if (!id) return;

  const wrap = document.createElement("div");
  wrap.className = "msg-row bot";

  const bubble = document.createElement("div");
  bubble.className = "bubble bot";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-primary btn-sm";
  btn.textContent = "📨 크리에이티브 채널에 Teams 전송";

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const prev = btn.textContent;
    btn.textContent = "전송 중…";
    try {
      const res = await fetch("/api/gdrive/notify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inspection_id: id }),
      });
      if (res.status === 401) {
        gdriveLoggedIn = false;
        document.body.classList.remove("auth-authenticated");
        renderGdriveComposerStatus(false);
        btn.textContent = prev;
        btn.disabled = false;
        addBubble(chatLog, "bot", "세션이 만료되었습니다. 다시 로그인해주세요.");
        return;
      }
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        btn.textContent = prev;
        btn.disabled = false;
        addBubble(chatLog, "bot", `Teams 전송 실패 (${res.status})\n${JSON.stringify(data) || ""}`);
        return;
      }
      btn.textContent = "✓ 전송됨";
      btn.disabled = true;
    } catch (e) {
      btn.textContent = prev;
      btn.disabled = false;
      addBubble(chatLog, "bot", `Teams 전송 에러: ${e}`);
    }
  });

  bubble.appendChild(btn);
  wrap.appendChild(bubble);
  logEl.appendChild(wrap);
  logEl.scrollTop = logEl.scrollHeight;
}

function addFigmaTeamsSendBar(logEl, inspection) {
  const id = inspection?.id;
  if (!id) return;

  const wrap = document.createElement("div");
  wrap.className = "msg-row bot";

  const bubble = document.createElement("div");
  bubble.className = "bubble bot";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-primary btn-sm";
  btn.textContent = "📨 크리에이티브 채널에 Teams 전송";

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const prev = btn.textContent;
    btn.textContent = "전송 중…";
    try {
      const res = await fetch("/api/figma/notify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inspection_id: id }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        btn.textContent = prev;
        btn.disabled = false;
        addBubble(chatLog, "bot", `Teams 전송 실패 (${res.status})\n${JSON.stringify(data) || ""}`);
        return;
      }
      if (data?.already_sent) {
        btn.textContent = "✓ 이미 전송됨";
        btn.disabled = true;
        return;
      }
      btn.textContent = "✓ 전송됨";
      btn.disabled = true;
    } catch (e) {
      btn.textContent = prev;
      btn.disabled = false;
      addBubble(chatLog, "bot", `Teams 전송 에러: ${e}`);
    }
  });

  bubble.appendChild(btn);
  wrap.appendChild(bubble);
  logEl.appendChild(wrap);
  logEl.scrollTop = logEl.scrollHeight;
}

// —— Utils ——
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 마크다운 스타일 헤딩(#…4) · **bold** · 줄바꿈. 입력은 먼저 escapeHtml. */
function formatBotMessage(text) {
  const esc = escapeHtml(text);
  return esc
    .replace(/^(#{1,4})\s+(.+)$/gm, "<strong>$2</strong>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function insertInlineImages(html, images, inspectionId, slackInspectionId, figmaInspectionId) {
  let out = html || "";
  const arr = Array.isArray(images) ? images : [];
  const useSlack =
    slackInspectionId != null && slackInspectionId !== undefined && String(slackInspectionId).trim() !== "";
  const useFigma =
    !useSlack &&
    figmaInspectionId != null &&
    figmaInspectionId !== undefined &&
    String(figmaInspectionId).trim() !== "";
  const useDbThumbs =
    !useSlack &&
    !useFigma &&
    inspectionId != null &&
    inspectionId !== undefined &&
    String(inspectionId).trim() !== "";
  arr.forEach((img, i) => {
    const n = i + 1;
    const tag = useSlack
      ? `<img src="/api/slack-inspection-image/${encodeURIComponent(String(slackInspectionId))}/${i}" class="inline-review-img" loading="lazy" alt="">`
      : useFigma
        ? `<img src="/api/figma/inspection-image/${encodeURIComponent(String(figmaInspectionId))}/${i}" class="inline-review-img" loading="lazy" alt="">`
        : useDbThumbs
          ? `<img src="/api/gdrive/inspection-image/${encodeURIComponent(String(inspectionId))}/${i}" class="inline-review-img" loading="lazy" alt="">`
          : `<img src="/api/gdrive/thumbnail/${encodeURIComponent(img.id)}" class="inline-review-img" loading="lazy" alt="">`;

    const patterns = [
      // ### 이미지 1 / ## 이미지 1 / # 이미지 1
      new RegExp(`(^|<br>)\\s*#{1,3}\\s*이미지\\s*${n}\\s*(<br>|$)`, "g"),
      // ### 📋 이미지 1 같은 케이스 (이모지/기호 0~4개 허용)
      new RegExp(`(^|<br>)\\s*#{1,3}\\s*[^<\\w\\d]{0,8}\\s*이미지\\s*${n}\\s*(<br>|$)`, "g"),
      // ### 이미지 N (파일명.jpg) — 헤딩에 파일명 넣은 레거시/오동작 출력
      new RegExp(`(^|<br>)\\s*#{1,3}\\s*이미지\\s*${n}\\s*\\([^)]*\\)\\s*(<br>|$)`, "g"),
      // ### 이미지 N `파일명`
      new RegExp(`(^|<br>)\\s*#{1,3}\\s*이미지\\s*${n}\\s*\`[^\`]*\`\\s*(<br>|$)`, "g"),
      // **이미지 1** → <strong>이미지 1</strong>
      new RegExp(`(^|<br>)\\s*<strong>\\s*이미지\\s*${n}\\s*<\\/strong>\\s*(<br>|$)`, "g"),
      new RegExp(`(^|<br>)\\s*<strong>\\s*이미지\\s*${n}\\s*\\([^)]*\\)\\s*<\\/strong>\\s*(<br>|$)`, "g"),
      new RegExp(`(^|<br>)\\s*<strong>\\s*이미지\\s*${n}\\s*\`[^\`]*\`\\s*<\\/strong>\\s*(<br>|$)`, "g"),
      // 마지막 방어: 라인 시작에 "이미지 1"만 있는 경우
      new RegExp(`(^|<br>)\\s*이미지\\s*${n}\\s*(<br>|$)`, "g"),
    ];

    for (const re of patterns) {
      const prev = out;
      out = out.replace(re, `$1${tag}<br><strong>이미지 ${n}</strong><br>`);
      if (out !== prev) break;
    }
  });
  return out;
}

function fileChipHtml(file) {
  if (!file) return "";
  const url = (file.url || "").trim();
  if (!url) return "";

  const et = (file.external_type || "").trim();
  const ft = (file.filetype || "").trim();
  const mm = (file.mimetype || "").trim();
  const name = (file.name || file.title || "").trim();

  const looksImage =
    mm.startsWith("image/") ||
    ["png", "jpg", "jpeg", "gif", "webp"].includes(ft.toLowerCase()) ||
    ["png", "jpg", "jpeg", "gif", "webp"].includes((et || "").toLowerCase());

  let cls = "file-chip file-chip-default";
  let icon = "📎";
  if (et === "google_sheets" || ft === "google_sheets") {
    cls = "file-chip file-chip-sheets";
    icon = "📊";
  } else if (et === "google_docs" || ft === "google_docs" || et === "google_slides" || ft === "google_slides") {
    cls = "file-chip file-chip-docs";
    icon = "📄";
  } else if (et === "figma" || ft === "figma") {
    cls = "file-chip file-chip-figma";
    icon = "🎨";
  } else if (looksImage || et === "slack_upload") {
    cls = "file-chip file-chip-image";
    icon = "🖼️";
  }

  const label = escapeHtml(name || url);
  const isSlackFileUrl = (() => {
    try {
      return new URL(url).hostname.includes("files.slack.com");
    } catch {
      return url.includes("files.slack.com");
    }
  })();
  const href = et === "slack_upload" || isSlackFileUrl ? `/api/files/download?url=${encodeURIComponent(url)}` : url;
  const target = et === "slack_upload" ? "" : ' target="_blank" rel="noopener noreferrer"';
  return `<a class="${cls}" href="${escapeHtml(href)}"${target}>${icon} ${label}</a>`;
}

function fileChipListHtml(files) {
  const arr = Array.isArray(files) ? files : [];
  if (!arr.length) return "";
  const chips = arr.map(fileChipHtml).filter(Boolean).join("");
  if (!chips) return "";
  return `<div class="file-chip-list">${chips}</div>`;
}

// Slack message ts(초 단위)를 KST로 표시
function slackTsToKST(ts) {
  if (!ts) return "";
  const ms = parseFloat(ts) * 1000;
  if (isNaN(ms)) return "";
  const d = new Date(ms + 9 * 3600 * 1000); // KST = UTC+9
  return d.toISOString().replace("T", " ").slice(0, 19);
}

/** 이미지 첨부 썸네일 (원본 메시지 / 히스토리 / 승인 모달 공통) */
function renderImageThumbnails(files, opts) {
  const options = opts || {};
  const wrapClass = options.wrapClass || "thumb-container";
  const imgClass = options.imgClass || "thumb-img";
  const arr = Array.isArray(files) ? files : [];
  const images = arr.filter((f) => {
    const mm = (f.mimetype || "").trim();
    const ft = (f.filetype || "").toLowerCase();
    return mm.startsWith("image/") || ["png", "jpg", "jpeg", "gif", "webp"].includes(ft);
  });
  if (!images.length) return "";
  const inner = images
    .map((f) => {
      const url = (f.url || "").trim();
      if (!url) return "";
      const et = (f.external_type || "").trim();
      let src = url;
      const isSlackFileUrl = (() => {
        try {
          return new URL(url).hostname.includes("files.slack.com");
        } catch {
          return url.includes("files.slack.com");
        }
      })();
      if (et === "slack_upload" || isSlackFileUrl) src = `/api/files/download?url=${encodeURIComponent(url)}`;
      const alt = f.name || f.title || "";
      return `<img src="${escapeHtml(src)}" class="${imgClass}" loading="lazy" alt="${escapeHtml(
        alt
      )}" onclick="event.stopPropagation(); openLightbox(this.src)">`;
    })
    .filter(Boolean)
    .join("");
  if (!inner) return "";
  return `<div class="${wrapClass}">${inner}</div>`;
}

/** History 카드·모달 뱃지용 상태 → CSS 클래스 */
function statusClass(status) {
  if (status === "활성") return "badge-활성";
  if (status === "변경됨") return "badge-변경됨";
  if (status === "폐기") return "badge-폐기";
  return "badge-활성";
}

/** 슬랙 승인 카드 뱃지 */
function approvalStatusBadgeClass(status) {
  const s = status || "대기중";
  if (s === "처리중") return "badge-처리중";
  if (s === "대기중") return "badge-대기중";
  return "badge-활성";
}

function formatCategoryLabel(c) {
  const s = c == null ? "" : String(c).trim();
  return s || "미분류";
}

function titleFallback(item) {
  const topic = (item?.topic || "").trim();
  if (topic) return topic;
  const ft = String(item?.full_text || "").trim();
  if (ft) {
    const first = ft.split("\n")[0].trim();
    if (first) return first.slice(0, 80);
  }
  return "(제목 없음)";
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === "className") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  });
  children.forEach((c) => {
    if (c) node.appendChild(c);
  });
  return node;
}

async function apiJson(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined && body !== null ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return null;
}

/** POST JSON — ok 시 본문 객체 반환, 실패 시 Error(detail) */
async function postJsonExpectOk(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined && body !== null ? JSON.stringify(body) : "{}",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data?.detail;
    if (res.status === 412 && detail && typeof detail === "object" && detail.code === "gdrive_auth_required") {
      showGdriveAuthModal(detail);
      const err = new Error(detail.message || "Google Drive 로그인 필요");
      err.code = "gdrive_auth_required";
      throw err;
    }
    let msg;
    if (typeof detail === "string") msg = detail;
    else if (Array.isArray(detail)) msg = detail.map((x) => x?.msg || x).join("; ");
    else msg = JSON.stringify(data) || String(res.status);
    throw new Error(msg);
  }
  return data;
}

function showGdriveAuthModal(detail) {
  const m = document.getElementById("gdriveAuthModal");
  const msg = document.getElementById("gdriveAuthModalMsg");
  if (msg && detail?.link_count != null) {
    msg.textContent = `Google 문서 링크가 ${detail.link_count}건 포함되어 있어 로그인이 필요합니다. 로그인 후 다시 승인을 눌러주세요.`;
  }
  m?.classList.remove("hidden");
}

document.getElementById("gdriveAuthLoginBtn")?.addEventListener("click", () => {
  window.location.href = "/api/gdrive/oauth/login";
});
document.getElementById("gdriveAuthCancelBtn")?.addEventListener("click", () => {
  document.getElementById("gdriveAuthModal")?.classList.add("hidden");
});

const gdriveModalEl = document.getElementById("gdriveAuthModal");
if (gdriveModalEl) {
  gdriveModalEl.addEventListener("click", (e) => {
    if (e.target === gdriveModalEl) gdriveModalEl.classList.add("hidden");
  });
}

function addBubble(logEl, role, text, meta = "", options = {}) {
  const wrap = document.createElement("div");
  wrap.className = `msg-row ${role === "user" ? "user" : "bot"}`;

  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  if (options.asHtml) bubble.innerHTML = text;
  else bubble.textContent = text;
  wrap.appendChild(bubble);

  if (meta) {
    const m = document.createElement("div");
    m.className = "msg-meta";
    m.textContent = meta;
    wrap.appendChild(m);
  }

  logEl.appendChild(wrap);
  logEl.scrollTop = logEl.scrollHeight;
}

function removeLastBubble(logEl) {
  const last = logEl.lastElementChild;
  if (last) last.remove();
}

/** User message for 소재 검수: optional images[] + optional text */
function appendInspectUserBubble(logEl, message, imageItems) {
  const wrap = document.createElement("div");
  wrap.className = "msg-row user";

  const bubble = document.createElement("div");
  bubble.className = "bubble user";

  const imgs = Array.isArray(imageItems)
    ? imageItems
    : imageItems && (imageItems.base64 || imageItems.dataUrl || imageItems.file)
        ? [imageItems]
        : [];
  const hasImg = imgs.length > 0;
  const hasText = Boolean(message);
  if (!hasImg && !hasText) return;

  for (const payload of imgs) {
    const mt = payload.mediaType || "image/png";
    const src =
      payload.dataUrl || (payload.base64 ? `data:${mt};base64,${payload.base64}` : "");
    if (!src) continue;
    if (payload.isVideo || mt.startsWith("video/")) {
      const vid = document.createElement("video");
      vid.className = "bubble-img";
      vid.controls = true;
      vid.muted = true;
      vid.playsInline = true;
      vid.src = src;
      bubble.appendChild(vid);
    } else {
      const img = document.createElement("img");
      img.className = "bubble-img";
      img.alt = "첨부 이미지";
      img.src = src;
      bubble.appendChild(img);
    }
  }
  if (hasText) {
    const span = document.createElement("span");
    span.className = "bubble-user-text";
    span.textContent = message;
    bubble.appendChild(span);
  }

  wrap.appendChild(bubble);
  logEl.appendChild(wrap);
  logEl.scrollTop = logEl.scrollHeight;
}

// —— Context panel ——
function renderContextInspect() {
  contextTitle.textContent = "분석 컨텍스트";
  if (!lastInspectResult) {
    contextBody.innerHTML =
      '<p class="context-stat"><span class="context-stat-label">상태</span><span class="context-stat-value">대기</span></p>' +
      "<p style=color:var(--on-surface-variant);font-size:13px;margin-top:12px>검수를 실행하면 rules_checked와 요약이 여기에 표시됩니다.</p>";
    return;
  }
  const { feedback, rules_checked } = lastInspectResult;
  const preview = escapeHtml(feedback.slice(0, 1200)) + (feedback.length > 1200 ? "…" : "");
  contextBody.innerHTML = `
    <div class="context-stat"><span class="context-stat-label">rules_checked</span><span class="context-stat-value">${escapeHtml(String(rules_checked))}</span></div>
    <p style="margin-top:14px;font-size:12px;color:var(--on-surface-variant)">피드백 미리보기</p>
    <div class="context-block">${preview.replace(/\n/g, "<br>")}</div>
  `;
}

function computeHistoryStats() {
  const statsList = historyRecordsAll;
  const n = statsList.length;
  const byStatus = { 활성: 0, 변경됨: 0, 폐기: 0 };
  statsList.forEach((h) => {
    const s = h.status || "";
    if (byStatus[s] !== undefined) byStatus[s] += 1;
  });
  const activeRate = n ? Math.round((byStatus["활성"] / n) * 100) : 0;
  return { n, byStatus, activeRate };
}

function updateHistoryStatsLine() {
  if (!historyChatStats) return;
  if (historySubTab === "raw") {
    const n = rawMessagesCache.length;
    const fl =
      rawFilterKind === "feedback"
        ? "피드백"
        : rawFilterKind === "not_feedback"
          ? "비피드백"
          : rawFilterKind === "bot"
            ? "봇"
            : "전체";
    const parts = [`필터: ${fl}`];
    const sq = (rawSearchQuery || "").trim();
    if (sq) parts.push(`검색: ${sq}`);
    const au = (rawAuthor || "").trim();
    if (au) parts.push(`작성자: ${au}`);
    if (rawHasFiles) parts.push("첨부있음");
    parts.push(rawOrder === "asc" ? "오래된순" : "최신순");
    historyChatStats.textContent =
      n === 0
        ? "표시할 원본 메시지가 없습니다."
        : `슬랙 원문 ${n}건 · ${parts.join(" · ")} (최대 100건)`;
    return;
  }
  const { n, byStatus, activeRate } = computeHistoryStats();
  historyChatStats.textContent =
    n === 0
      ? "등록된 히스토리가 없습니다."
      : `총 ${n}건 · 활성 ${activeRate}% · 변경 ${byStatus["변경됨"]} · 폐기 ${byStatus["폐기"]}`;
}

function renderContextHistory() {
  contextTitle.textContent = historySubTab === "raw" ? "슬랙 원문" : "히스토리 통계";
  contextBody.innerHTML = "";
  updateHistoryStatsLine();
}

function renderContextTerms() {
  contextTitle.textContent = "용어 컨텍스트";
  if (!recentTerms.length) {
    contextBody.innerHTML =
      '<p style="color:var(--on-surface-variant);font-size:13px">용어 해석 대화에서 보낸 문장이 최근 목록으로 쌓입니다.</p>';
    return;
  }
  const items = recentTerms
    .map((t) => `<li style="margin:6px 0;font-size:13px">${escapeHtml(t)}</li>`)
    .join("");
  contextBody.innerHTML = `<p style="font-size:12px;font-weight:600;color:var(--on-surface-variant)">최근 조회</p><ul style="padding-left:18px;margin:8px 0">${items}</ul>`;
}

function renderContextManual() {
  contextTitle.textContent = "수동 적재";
  contextBody.innerHTML =
    '<p style="font-size:13px;color:var(--on-surface-variant);line-height:1.55">본문만 입력하면 <strong>히스토리에 바로 적재</strong>됩니다. 문서 URL은 적재 시 자동으로 읽어 refine에 반영됩니다. 5~30초 소요될 수 있습니다.</p>';
}

function renderContextAdmin() {
  contextTitle.textContent = "승인 현황";
  const pending = adminListCache.filter((x) => (x.status || "") === "대기중").length;
  const processing = adminListCache.filter((x) => (x.status || "") === "처리중").length;
  const conflicts = adminListCache.filter((x) => Number(x.has_conflict) === 1).length;
  const shown = adminListCache.length;
  contextBody.innerHTML = `
    <div class="context-stat"><span class="context-stat-label">조건 일치</span><span class="context-stat-value">${adminTotal}건</span></div>
    <p style="margin:10px 0 6px;font-size:12px;color:var(--on-surface-variant)"><strong>현재 표시 중</strong> ${shown}건 — 대기 ${pending} · 처리 ${processing} · 충돌 ${conflicts}</p>
    <p style="margin-top:14px;font-size:12px;color:var(--on-surface-variant)">카드를 눌러 상세 모달에서 승인·폐기할 수 있습니다. 처리중인 카드는 완료될 때까지 열 수 없습니다.</p>
  `;
}

function updateContextPanel() {
  if (currentView === "inspect") renderContextInspect();
  else if (currentView === "history") renderContextHistory();
  else if (currentView === "terms") renderContextTerms();
  else if (currentView === "manual") renderContextManual();
  else if (currentView === "admin") renderContextAdmin();
}

// —— View switching ——
function switchView(name) {
  if (!VIEWS.includes(name)) return;
  closeHistoryModal();
  closeAdminModal();
  currentView = name;

  if (appRoot) {
    appRoot.classList.toggle("hide-context", name === "history");
  }

  document.querySelectorAll(".content .view").forEach((sec) => {
    sec.classList.toggle("view-active", sec.id === `view-${name}`);
  });

  document.querySelectorAll(".sidebar-nav [data-view]").forEach((a) => {
    a.classList.toggle("active", a.dataset.view === name);
  });

  viewTitle.textContent = VIEW_TITLES[name] || name;

  if (adminPollTimer) {
    clearInterval(adminPollTimer);
    adminPollTimer = null;
  }
  if (name === "admin") {
    loadAdmin({ append: false });
    // adminPollTimer = setInterval(() => loadAdmin({ append: false }), 30000);
  }

  if (name === "history") {
    if (historySubTab === "raw") loadRawMessages();
    else loadHistory();
  }

  if (name === "copywriter") {
    ensureCopywriterDefaultPicker();
  }

  updateContextPanel();
}

document.querySelectorAll(".sidebar-nav [data-view]").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    switchView(a.dataset.view);
  });
});

// —— New inspection ——
function resetInspectSession() {
  chatLog.innerHTML = "";
  textInput.value = "";
  clearLocalInspectImages();
  imagePreview.classList.add("hidden");
  imagePreview.innerHTML = "";
  lastInspectResult = null;
  addBubble(
    chatLog,
    "bot",
    formatBotMessage(
      "새 검수 세션입니다.\n구글 드라이브 폴더 URL을 입력하거나, 로컬 이미지를 첨부한 뒤 전송하세요.\nEnter 전송 · Shift+Enter 줄바꿈"
    ),
    "",
    { asHtml: true }
  );
  updateContextPanel();
}

btnNewInspection.addEventListener("click", () => {
  switchView("inspect");
  resetInspectSession();
});

// —— Inspect ——
function readFileAsImageItem(file) {
  const mt = file.type || "image/png";
  if (mt.startsWith("video/")) {
    return Promise.resolve({
      base64: null,
      mediaType: mt,
      dataUrl: URL.createObjectURL(file),
      file,
      name: file.name,
      size: file.size,
      isVideo: true,
    });
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      const commaIdx = dataUrl.indexOf(",");
      const b64 = commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : dataUrl;
      resolve({
        base64: b64,
        mediaType: mt,
        dataUrl,
        file,
        name: file.name,
        size: file.size,
        isVideo: false,
      });
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function renderInspectImagePreview() {
  if (!inspectImageList.length) {
    imagePreview.classList.add("hidden");
    imagePreview.innerHTML = "";
    return;
  }
  imagePreview.classList.remove("hidden");
  imagePreview.innerHTML = "";
  const row = document.createElement("div");
  row.className = "image-preview-row";

  inspectImageList.forEach((item) => {
    const wrap = document.createElement("div");
    wrap.className = "image-preview-item";
    let mediaEl;
    if (item.isVideo) {
      mediaEl = document.createElement("video");
      mediaEl.controls = true;
      mediaEl.muted = true;
      mediaEl.playsInline = true;
      mediaEl.src = item.dataUrl;
    } else {
      const img = document.createElement("img");
      img.src = item.dataUrl;
      img.alt = item.name || "";
      mediaEl = img;
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "image-preview-remove";
    btn.setAttribute("aria-label", "첨부 제거");
    btn.textContent = "×";
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const i = inspectImageList.indexOf(item);
      if (i >= 0) {
        revokeInspectBlobUrl(inspectImageList[i]);
        inspectImageList.splice(i, 1);
      }
      renderInspectImagePreview();
    });
    const cap = document.createElement("div");
    cap.className = "image-preview-caption";
    cap.textContent = `${item.name || "file"} (${Math.round(item.size / 1024)}KB)`;
    wrap.appendChild(mediaEl);
    wrap.appendChild(btn);
    wrap.appendChild(cap);
    row.appendChild(wrap);
  });

  imagePreview.appendChild(row);
}

imageInput.addEventListener("change", async (e) => {
  const files = e.target.files;
  if (!files?.length) {
    inspectImageList.forEach(revokeInspectBlobUrl);
    inspectImageList = [];
    renderInspectImagePreview();
    return;
  }
  const imageFiles = Array.from(files).filter(
    (f) => f.type && (f.type.startsWith("image/") || f.type.startsWith("video/"))
  );
  if (!imageFiles.length) {
    alert("이미지·영상 파일만 업로드 가능합니다.");
    e.target.value = "";
    return;
  }
  const room = Math.max(0, MAX_INSPECT_IMAGES - inspectImageList.length);
  if (room <= 0) {
    alert(`첨부는 최대 ${MAX_INSPECT_IMAGES}개까지 가능합니다.`);
    e.target.value = "";
    return;
  }
  const take = imageFiles.slice(0, room);
  if (imageFiles.length > room) {
    alert(`첨부는 최대 ${MAX_INSPECT_IMAGES}개까지입니다. 나머지는 제외했습니다.`);
  }
  try {
    for (const file of take) {
      if (file.size >= MAX_INSPECT_UPLOAD_BYTES) {
        alert(
          "파일이 너무 큽니다 (최대 500MB)\n영상은 서버에서 압축하니, 500MB 미만 원본을 그대로 올려 주세요."
        );
        continue;
      }
      const item = await readFileAsImageItem(file);
      inspectImageList.push(item);
    }
  } catch (err) {
    alert(`파일 읽기 실패: ${err}`);
  }
  e.target.value = "";
  renderInspectImagePreview();
});

async function sendInspect() {
  const rawMessage = (textInput.value || "").trim();
  const folderId = parseDriveFolderId(rawMessage);
  const figmaParsed = parseFigmaUrl(rawMessage);
  const hasLocal = inspectImageList.length > 0;

  if (!rawMessage && !hasLocal) return;

  if (folderId) {
    if (hasLocal) {
      alert("드라이브 폴더 검수를 사용합니다. 로컬 첨부를 제거했습니다.");
      clearLocalInspectImages();
      if (imageInput) imageInput.value = "";
      renderInspectImagePreview();
    }
    if (!gdriveLoggedIn) {
      alert("구글 로그인이 필요합니다.");
      window.location = "/api/gdrive/oauth/login";
      return;
    }

    addBubble(chatLog, "user", rawMessage);
    textInput.value = "";
    sendBtn.disabled = true;

    addBubble(chatLog, "bot", "드라이브에서 이미지를 가져오는 중...", "잠시만 기다려주세요");

    try {
      const res = await fetch("/api/gdrive/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          folder_id: folderId,
          file_ids: null,
          message: rawMessage || null,
        }),
      });

      removeLastBubble(chatLog);

      if (res.status === 401) {
        gdriveLoggedIn = false;
        renderGdriveComposerStatus(false);
        addBubble(chatLog, "bot", "세션이 만료되었습니다. 다시 로그인해주세요.");
        return;
      }

      if (!res.ok) {
        const text = await res.text();
        addBubble(chatLog, "bot", `요청 실패 (${res.status})\n${text}`);
        return;
      }

      const data = await res.json();
      lastInspectResult = { feedback: data.feedback, rules_checked: data.rules_checked };
      const imgN = data.image_count != null ? data.image_count : data.file_count;
      const vidN = data.video_count != null ? data.video_count : 0;
      const meta = `검수 ${data.file_count ?? "?"}건 (이미지 ${imgN ?? "?"} · 영상 ${vidN}) · 폴더 후보 ${data.total_in_folder ?? "?"}건 · rules_checked: ${data.rules_checked ?? "?"}`;
      const driveImgMeta = (data.images || []).filter((x) => !x.kind || x.kind === "image");
      const html = insertInlineImages(formatBotMessage(data.feedback || ""), driveImgMeta, data.id, null, null);
      addBubble(chatLog, "bot", html, meta, { asHtml: true });
      addTeamsSendBar(chatLog, data);
      updateContextPanel();
    } catch (e) {
      removeLastBubble(chatLog);
      addBubble(chatLog, "bot", `에러: ${e}`);
    } finally {
      sendBtn.disabled = false;
    }
    return;
  }

  if (figmaParsed?.fileKey) {
    if (hasLocal) {
      alert("Figma URL 검수를 사용합니다. 로컬 첨부를 제거했습니다.");
      clearLocalInspectImages();
      if (imageInput) imageInput.value = "";
      renderInspectImagePreview();
    }
    if (!figmaParsed.nodeId) {
      alert("프레임을 지정해주세요. Figma에서 프레임을 선택한 뒤 URL을 복사하세요.");
      return;
    }

    addBubble(chatLog, "user", rawMessage);
    textInput.value = "";
    sendBtn.disabled = true;

    addBubble(chatLog, "bot", "Figma에서 프레임 이미지를 가져오는 중...", "잠시만 기다려주세요");

    try {
      const res = await fetch("/api/figma/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_key: figmaParsed.fileKey,
          node_id: figmaParsed.nodeId,
          message: rawMessage || null,
          figma_url: rawMessage || null,
        }),
      });

      removeLastBubble(chatLog);

      if (!res.ok) {
        const text = await res.text();
        addBubble(chatLog, "bot", `요청 실패 (${res.status})\n${text}`);
        return;
      }

      const data = await res.json();
      lastInspectResult = { feedback: data.feedback, rules_checked: data.rules_checked };
      const meta = `Figma · rules_checked: ${data.rules_checked ?? "?"}`;
      const html = insertInlineImages(
        formatBotMessage(data.feedback || ""),
        data.images || [],
        null,
        null,
        data.id
      );
      addBubble(chatLog, "bot", html, meta, { asHtml: true });
      addFigmaTeamsSendBar(chatLog, data);
      updateContextPanel();
    } catch (e) {
      removeLastBubble(chatLog);
      addBubble(chatLog, "bot", `에러: ${e}`);
    } finally {
      sendBtn.disabled = false;
    }
    return;
  }

  const imagesCopy = [...inspectImageList];
  appendInspectUserBubble(chatLog, rawMessage, imagesCopy);
  textInput.value = "";
  sendBtn.disabled = true;

  const hasVideo = imagesCopy.some((x) => x.isVideo);
  const loadMsg = hasVideo
    ? "영상 처리 중입니다… (업로드·분석에 수십 초 걸릴 수 있습니다)"
    : "응답을 생성 중입니다...";
  addBubble(chatLog, "bot", loadMsg, "잠시만 기다려주세요");

  try {
    let res;
    if (imagesCopy.length > 0) {
      for (const item of imagesCopy) {
        if (item.file && item.file.size >= MAX_INSPECT_UPLOAD_BYTES) {
          removeLastBubble(chatLog);
          addBubble(
            chatLog,
            "bot",
            "파일이 너무 큽니다 (최대 500MB)\n영상은 서버에서 압축하니, 500MB 미만 원본을 그대로 올려 주세요."
          );
          return;
        }
      }
      const formData = new FormData();
      for (const item of imagesCopy) {
        if (!item.file) {
          removeLastBubble(chatLog);
          addBubble(chatLog, "bot", "첨부 파일 정보가 없습니다. 다시 선택해 주세요.");
          return;
        }
        formData.append("files", item.file, item.name || "file");
      }
      formData.append("message", rawMessage || "이 소재를 검수해주세요.");
      formData.append("mode", "소재검수");
      res = await fetch("/api/inspect-upload", {
        method: "POST",
        body: formData,
      });
    } else {
      const body = {
        message: rawMessage || "이 소재를 검수해주세요.",
        mode: "소재검수",
      };
      res = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }

    removeLastBubble(chatLog);

    if (!res.ok) {
      const text = await res.text();
      addBubble(chatLog, "bot", `요청 실패 (${res.status})\n${text}`);
      return;
    }

    const data = await res.json();
    lastInspectResult = { feedback: data.feedback, rules_checked: data.rules_checked };
    addBubble(chatLog, "bot", formatBotMessage(data.feedback), `rules_checked: ${data.rules_checked}`, {
      asHtml: true,
    });
    updateContextPanel();
  } catch (e) {
    removeLastBubble(chatLog);
    addBubble(chatLog, "bot", `에러: ${e}`);
  } finally {
    sendBtn.disabled = false;
    clearLocalInspectImages();
    renderInspectImagePreview();
  }
}

sendBtn.addEventListener("click", sendInspect);
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendInspect();
  }
});

function renderGdriveComposerStatus(loggedIn, email) {
  if (!gdriveComposerStatus) return;
  if (loggedIn) {
    gdriveComposerStatus.innerHTML = `연결됨${
      email ? ` <span style="opacity:.85">(${escapeHtml(email)})</span>` : ""
    } · <button type="button" class="btn btn-ghost btn-sm gdrive-logout-btn">로그아웃</button>`;
  } else {
    gdriveComposerStatus.innerHTML =
      '<a class="gdrive-composer-link" href="/api/gdrive/oauth/login">Google 로그인</a>';
  }
}

async function checkGdriveAuthStatus() {
  try {
    const st = await apiJson("GET", "/api/gdrive/oauth/status", null);
    gdriveLoggedIn = Boolean(st?.logged_in);
    renderGdriveComposerStatus(gdriveLoggedIn, st?.user_email);
    if (gdriveLoggedIn) {
      document.body.classList.add("auth-authenticated");
    } else {
      document.body.classList.remove("auth-authenticated");
    }
  } catch {
    gdriveLoggedIn = false;
    renderGdriveComposerStatus(false);
    document.body.classList.remove("auth-authenticated");
  }
}

if (gdriveComposerStatus) {
  gdriveComposerStatus.addEventListener("click", async (e) => {
    const btn = e.target.closest(".gdrive-logout-btn");
    if (!btn) return;
    e.preventDefault();
    try {
      await apiJson("DELETE", "/api/gdrive/oauth/logout", null);
    } catch {
      // ignore
    }
    gdriveLoggedIn = false;
    document.body.classList.remove("auth-authenticated");
    renderGdriveComposerStatus(false);
  });
}

// —— History detail modal ——
function syncHistoryModalHeader(item) {
  if (!item) return;
  historyModalTitle.textContent = `#${item.id} ${titleFallback(item)}`;
  const st = item.status || "—";
  historyModalBadge.textContent = st;
  historyModalBadge.className = `modal-badge badge-status ${statusClass(st)}`;
  if (historyModalMeta) {
    const cat = formatCategoryLabel(item.category);
    historyModalMeta.textContent = `${item.message_time || item.date || ""} · ${item.author_name || item.author_user_id || "—"} · ${item.scope || ""} · ${item.type || ""} · ${cat}`;
  }
}

function renderHistoryModalRead() {
  const item = historyModalCurrentItem;
  if (!item || !historyModalBody) return;
  isEditingHistory = false;
  syncHistoryModalHeader(item);
  historyModalBody.className = "modal-body modal-body--read";
  const body = item.summary || item.full_text || "";
  const thumbsHtml = renderImageThumbnails(item.files || []);
  const filesHtml = fileChipListHtml(item.files || []);
  historyModalBody.innerHTML = body
    ? `<div class="modal-read">${formatBotMessage(body)}</div>${thumbsHtml}${filesHtml}`
    : `<p class="modal-empty">내용이 없습니다.</p>${thumbsHtml}${filesHtml}`;
  historyModalActionsRead?.classList.remove("hidden");
  historyModalActionsEdit?.classList.add("hidden");
}

function historyModalFieldRow(labelText, inputEl) {
  const wrap = el("div");
  const lbl = document.createElement("label");
  lbl.textContent = labelText;
  if (inputEl.id) lbl.setAttribute("for", inputEl.id);
  wrap.appendChild(lbl);
  wrap.appendChild(inputEl);
  return wrap;
}

function renderHistoryModalEdit() {
  const item = historyModalCurrentItem;
  if (!item || !historyModalBody) return;
  isEditingHistory = true;
  syncHistoryModalHeader(item);
  historyModalBody.className = "modal-body";
  historyModalBody.innerHTML = "";

  const form = el("div", { className: "modal-edit-form" });

  const topicIn = el("input", { type: "text", id: "historyEditTopic" });
  topicIn.value = item.topic || "";
  form.appendChild(historyModalFieldRow("주제", topicIn));

  const sumTa = el("textarea", { id: "historyEditSummary", rows: "3" });
  sumTa.value = item.summary || "";
  form.appendChild(historyModalFieldRow("요약", sumTa));

  const scopeSel = el("select", { id: "historyEditScope" });
  HISTORY_SCOPE_OPTIONS.forEach((s) => {
    const opt = el("option", { value: s, text: s });
    if (item.scope === s) opt.selected = true;
    scopeSel.appendChild(opt);
  });
  form.appendChild(historyModalFieldRow("scope", scopeSel));

  const typeSel = el("select", { id: "historyEditType" });
  HISTORY_TYPE_OPTIONS.forEach((t) => {
    const opt = el("option", { value: t, text: t });
    if (item.type === t) opt.selected = true;
    typeSel.appendChild(opt);
  });
  form.appendChild(historyModalFieldRow("type", typeSel));

  const catSel = el("select", { id: "historyEditCategory" });
  const curRaw = (item.category || "").trim();
  const curCat = HISTORY_CATEGORY_OPTIONS.includes(curRaw) ? curRaw : "크리에이티브";
  HISTORY_CATEGORY_OPTIONS.forEach((c) => {
    const opt = el("option", { value: c, text: c });
    if (c === curCat) opt.selected = true;
    catSel.appendChild(opt);
  });
  form.appendChild(historyModalFieldRow("적재 카테고리", catSel));

  const fullTa = el("textarea", {
    id: "historyEditFullText",
    className: "modal-field-tall",
    rows: "8",
  });
  fullTa.value = item.full_text || "";
  form.appendChild(historyModalFieldRow("전문", fullTa));

  const quoteTa = el("textarea", { id: "historyEditOriginalQuote", rows: "3" });
  quoteTa.value = item.original_quote || "";
  form.appendChild(historyModalFieldRow("원문 인용", quoteTa));

  historyModalBody.appendChild(form);
  historyModalActionsRead?.classList.add("hidden");
  historyModalActionsEdit?.classList.remove("hidden");
}

function openHistoryModal(item) {
  if (!historyModal || !item) return;
  closeAdminModal();
  historyModalCurrentItem = { ...item };
  isEditingHistory = false;
  renderHistoryModalRead();
  historyModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeHistoryModal(force = false) {
  if (!force && isEditingHistory) {
    if (!confirm("수정 내용이 저장되지 않습니다. 닫으시겠습니까?")) return;
  }
  isEditingHistory = false;
  historyModalCurrentItem = null;
  if (historyModal) historyModal.classList.add("hidden");
  document.body.style.overflow = "";
}

async function historyModalSaveHandler() {
  const item = historyModalCurrentItem;
  if (!item?.id) return;
  const topic = document.getElementById("historyEditTopic")?.value?.trim() ?? "";
  const summary = document.getElementById("historyEditSummary")?.value?.trim() ?? "";
  const scope = document.getElementById("historyEditScope")?.value;
  const typ = document.getElementById("historyEditType")?.value;
  const category = document.getElementById("historyEditCategory")?.value;
  const full_text = document.getElementById("historyEditFullText")?.value ?? "";
  const original_quote = document.getElementById("historyEditOriginalQuote")?.value ?? "";
  if (!topic) {
    alert("주제를 입력하세요.");
    return;
  }
  if (!summary) {
    alert("요약을 입력하세요.");
    return;
  }
  try {
    await apiJson("PUT", `/api/history/${item.id}`, {
      topic,
      summary,
      scope,
      type: typ,
      category: category || null,
      full_text: full_text || null,
      original_quote: original_quote || null,
    });
    await loadHistory();
    closeHistoryModal(true);
  } catch (e) {
    alert(`저장 실패: ${e.message}`);
  }
}

async function historyModalDeleteHandler() {
  const item = historyModalCurrentItem;
  if (!item?.id) return;
  if (!confirm("정말 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.")) return;
  try {
    await apiJson("DELETE", `/api/history/${item.id}`, undefined);
    if (selectedHistoryId === item.id) selectedHistoryId = null;
    await loadHistory();
    closeHistoryModal(true);
  } catch (e) {
    alert(`삭제 실패: ${e.message}`);
  }
}

if (historyModal && historyModalClose) {
  historyModalClose.addEventListener("click", () => closeHistoryModal());

  historyModal.addEventListener("click", (e) => {
    if (e.target === historyModal) closeHistoryModal();
  });

  if (historyModalCard) {
    historyModalCard.addEventListener("click", (e) => e.stopPropagation());
  }
}

historyModalEdit?.addEventListener("click", () => renderHistoryModalEdit());
historyModalCancel?.addEventListener("click", () => renderHistoryModalRead());
historyModalSave?.addEventListener("click", () => historyModalSaveHandler());
historyModalDelete?.addEventListener("click", () => historyModalDeleteHandler());

function closeAdminModal() {
  adminModalCurrentItem = null;
  if (adminModal) adminModal.classList.add("hidden");
  if (!historyModal || historyModal.classList.contains("hidden")) {
    document.body.style.overflow = "";
  }
}

const ADMIN_BG_PROCESSING_MSG = "히스토리 적재를 백그라운드에서 처리 중입니다. 잠시 후 목록이 갱신됩니다.";

function adminModalCategoryBody() {
  const sel = document.getElementById("adminModalCategory");
  const v = sel?.value;
  return { category: v && String(v).trim() ? v : null };
}

function setAdminModalButtonsBusy(busy) {
  if (!adminModalActions) return;
  adminModalActions.querySelectorAll("button").forEach((b) => {
    b.disabled = busy;
  });
}

function wireAdminModalActions(item) {
  if (!adminModalActions || !item) return;
  adminModalActions.innerHTML = "";

  if (adminModalConflict) {
    if (Number(item.has_conflict) === 1) {
      adminModalConflict.textContent = `충돌: ${item.conflict_explanation || ""}`;
      adminModalConflict.classList.remove("hidden");
    } else {
      adminModalConflict.textContent = "";
      adminModalConflict.classList.add("hidden");
    }
  }

  const approve = el("button", { type: "button", className: "btn btn-primary btn-sm", text: "승인(적재)" });
  approve.addEventListener("click", async () => {
    const prevApproveLabel = approve.textContent;
    adminStatus.textContent = "요청 중...";
    setAdminModalButtonsBusy(true);
    approve.textContent = "요청 중…";
    try {
      const data = await postJsonExpectOk(`/api/approvals/${item.id}/approve`, adminModalCategoryBody());
      if (data?.status === "processing") {
        adminStatus.textContent = ADMIN_BG_PROCESSING_MSG;
        await loadAdmin();
        closeAdminModal();
        setAdminModalButtonsBusy(false);
        approve.textContent = prevApproveLabel;
        return;
      }
      await loadAdmin();
      closeAdminModal();
    } catch (e) {
      if (e.code === "gdrive_auth_required") {
        setAdminModalButtonsBusy(false);
        approve.textContent = prevApproveLabel;
        return;
      }
      adminStatus.textContent = `에러: ${e.message}`;
      setAdminModalButtonsBusy(false);
      approve.textContent = prevApproveLabel;
    }
    setAdminModalButtonsBusy(false);
    approve.textContent = prevApproveLabel;
  });

  const reject = el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "폐기" });
  reject.addEventListener("click", async () => {
    adminStatus.textContent = "처리 중...";
    setAdminModalButtonsBusy(true);
    try {
      await apiJson("POST", `/api/approvals/${item.id}/reject`, {});
      await loadAdmin();
      closeAdminModal();
    } catch (e) {
      adminStatus.textContent = `에러: ${e.message}`;
      setAdminModalButtonsBusy(false);
    }
  });

  adminModalActions.appendChild(approve);
  adminModalActions.appendChild(reject);

  const inspectTeams = el("button", {
    type: "button",
    className: "btn btn-ghost btn-sm",
    text: "🔍 검수 + Teams 전송",
  });
  inspectTeams.addEventListener("click", async () => {
    const prevLabel = inspectTeams.textContent;
    adminStatus.textContent = "검수 중...";
    setAdminModalButtonsBusy(true);
    inspectTeams.textContent = "검수 중...";
    try {
      const res = await apiJson("POST", `/api/approvals/${item.id}/inspect-and-notify`, {});
      if (res?.already_sent) {
        adminStatus.textContent = "이미 Teams로 전송된 항목입니다.";
        inspectTeams.textContent = prevLabel;
        setAdminModalButtonsBusy(false);
        return;
      }
      inspectTeams.textContent = "✓ 전송됨";
      const sid = res?.slack_inspection_id;
      adminStatus.textContent =
        sid != null ? `전송 완료 · 검수 #${sid}` : "전송 완료";
    } catch (e) {
      adminStatus.textContent = `에러: ${e.message}`;
      inspectTeams.textContent = prevLabel;
    }
    setAdminModalButtonsBusy(false);
  });
  adminModalActions.appendChild(inspectTeams);

  const saveCopybank = el("button", {
    type: "button",
    className: "btn btn-ghost btn-sm",
    text: "📝 카피뱅크 저장",
  });
  saveCopybank.addEventListener("click", async () => {
    const prev = saveCopybank.textContent;
    adminStatus.textContent = "저장 중...";
    setAdminModalButtonsBusy(true);
    saveCopybank.textContent = "저장 중…";
    try {
      const copy_text =
        String(item.full_text || "").trim() ||
        String(item.original_quote || "").trim() ||
        String(item.summary || "").trim();
      if (!copy_text) {
        adminStatus.textContent = "저장할 텍스트가 없습니다.";
        saveCopybank.textContent = prev;
        setAdminModalButtonsBusy(false);
        return;
      }
      await postJsonExpectOk("/api/copybank", { copy_text, source: "slack" });
      saveCopybank.textContent = "✓ 카피뱅크에 저장됨";
      adminStatus.textContent = "저장 완료";
      saveCopybank.disabled = true;
    } catch (e) {
      adminStatus.textContent = `에러: ${e.message}`;
      saveCopybank.textContent = prev;
    }
    setAdminModalButtonsBusy(false);
  });
  adminModalActions.appendChild(saveCopybank);

  if (Number(item.has_conflict) === 1) {
    const useNew = el("button", { type: "button", className: "btn btn-primary btn-sm", text: "신규로 교체" });
    useNew.addEventListener("click", async () => {
      const prev = useNew.textContent;
      adminStatus.textContent = "요청 중...";
      setAdminModalButtonsBusy(true);
      useNew.textContent = "요청 중…";
      try {
        const data = await postJsonExpectOk(`/api/approvals/${item.id}/conflict`, {
          action: "use_new",
          ...adminModalCategoryBody(),
        });
        if (data?.status === "processing") {
          adminStatus.textContent = ADMIN_BG_PROCESSING_MSG;
          await loadAdmin();
          closeAdminModal();
          setAdminModalButtonsBusy(false);
          useNew.textContent = prev;
          return;
        }
        await loadAdmin();
        closeAdminModal();
      } catch (e) {
        if (e.code === "gdrive_auth_required") {
          setAdminModalButtonsBusy(false);
          useNew.textContent = prev;
          return;
        }
        adminStatus.textContent = `에러: ${e.message}`;
        setAdminModalButtonsBusy(false);
        useNew.textContent = prev;
      }
      setAdminModalButtonsBusy(false);
      useNew.textContent = prev;
    });
    const keepOld = el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "기존 유지" });
    keepOld.addEventListener("click", async () => {
      adminStatus.textContent = "처리 중...";
      setAdminModalButtonsBusy(true);
      try {
        await apiJson("POST", `/api/approvals/${item.id}/conflict`, { action: "keep_old" });
        await loadAdmin();
        closeAdminModal();
      } catch (e) {
        adminStatus.textContent = `에러: ${e.message}`;
        setAdminModalButtonsBusy(false);
      }
    });
    const keepBoth = el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "둘 다 병기" });
    keepBoth.addEventListener("click", async () => {
      const prev = keepBoth.textContent;
      adminStatus.textContent = "요청 중...";
      setAdminModalButtonsBusy(true);
      keepBoth.textContent = "요청 중…";
      try {
        const data = await postJsonExpectOk(`/api/approvals/${item.id}/conflict`, {
          action: "keep_both",
          ...adminModalCategoryBody(),
        });
        if (data?.status === "processing") {
          adminStatus.textContent = ADMIN_BG_PROCESSING_MSG;
          await loadAdmin();
          closeAdminModal();
          setAdminModalButtonsBusy(false);
          keepBoth.textContent = prev;
          return;
        }
        await loadAdmin();
        closeAdminModal();
      } catch (e) {
        if (e.code === "gdrive_auth_required") {
          setAdminModalButtonsBusy(false);
          keepBoth.textContent = prev;
          return;
        }
        adminStatus.textContent = `에러: ${e.message}`;
        setAdminModalButtonsBusy(false);
        keepBoth.textContent = prev;
      }
      setAdminModalButtonsBusy(false);
      keepBoth.textContent = prev;
    });
    adminModalActions.appendChild(useNew);
    adminModalActions.appendChild(keepOld);
    adminModalActions.appendChild(keepBoth);
  }
}

function openAdminModal(item) {
  if (!adminModal || !item) return;
  closeHistoryModal(true);
  adminModalCurrentItem = { ...item };
  const quote = item.full_text || item.original_quote || item.summary || "";
  const imagesTop = renderImageThumbnails(item.files || [], {
    wrapClass: "admin-modal-images",
    imgClass: "admin-modal-thumb",
  });
  const filesHtml = fileChipListHtml(item.files || []);
  adminModalTitle.textContent = `${titleFallback(item)} (#${item.id})`;
  adminModalBody.innerHTML = `${imagesTop}<div class="modal-body-admin-text modal-read">${quote ? formatBotMessage(quote) : '<p class="modal-empty">내용이 없습니다.</p>'}</div>${filesHtml}`;

  if (adminModalMeta) {
    const cat = formatCategoryLabel(item.category);
    adminModalMeta.textContent = `${item.message_time || item.date || ""} · ${item.author_name || item.author_user_id || "—"} · ${item.scope || ""} · ${item.type || ""} · ${cat}`;
  }

  const adminCat = document.getElementById("adminModalCategory");
  if (adminCat) {
    const v = (item.category || "").trim();
    adminCat.value = HISTORY_CATEGORY_OPTIONS.includes(v) ? v : "크리에이티브";
  }

  wireAdminModalActions(item);
  adminModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

if (adminModal && adminModalClose) {
  adminModalClose.addEventListener("click", () => closeAdminModal());
  adminModal.addEventListener("click", (e) => {
    if (e.target === adminModal) closeAdminModal();
  });
  if (adminModalCard) {
    adminModalCard.addEventListener("click", (e) => e.stopPropagation());
  }
}

function openLightbox(src) {
  const url = (src || "").trim();
  if (!lightbox || !lightboxImg || !url) return;
  lightboxImg.src = url;
  lightboxImg.alt = "";
  lightbox.classList.remove("hidden");
}

function closeLightbox() {
  if (!lightbox || !lightboxImg) return;
  lightbox.classList.add("hidden");
  lightboxImg.removeAttribute("src");
  lightboxImg.alt = "";
}

if (lightbox && lightboxImg && lightboxClose) {
  lightboxClose.addEventListener("click", (e) => {
    e.stopPropagation();
    closeLightbox();
  });
  lightbox.addEventListener("click", (e) => {
    if (e.target === lightbox) closeLightbox();
  });
  lightboxImg.addEventListener("click", (e) => e.stopPropagation());
}

// ESC: lightbox > adminModal > historyModal (body overflow는 라이트박스에서 변경하지 않음)
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (lightbox && !lightbox.classList.contains("hidden")) {
    closeLightbox();
    return;
  }
  if (adminModal && !adminModal.classList.contains("hidden")) {
    closeAdminModal();
    return;
  }
  if (!historyModal || historyModal.classList.contains("hidden")) return;
  closeHistoryModal();
});

// —— History list + chat ——
function rawKindBadge(item) {
  if (Number(item.is_bot) === 1) return { cls: "badge-raw-bot", label: "봇" };
  if (item.is_feedback === 1 || item.is_feedback === "1") return { cls: "badge-raw-feedback", label: "피드백" };
  if (item.is_feedback === 0 || item.is_feedback === "0") return { cls: "badge-raw-not", label: "비피드백" };
  return { cls: "badge-raw-pending", label: "미분류" };
}

function setHistorySubTab(sub) {
  if (sub !== "history" && sub !== "raw") return;
  historySubTab = sub;

  document.querySelectorAll("#view-history .subtab-pill").forEach((b) => {
    b.classList.toggle("active", b.dataset.subtab === sub);
  });

  historyFilters.classList.toggle("hidden", sub !== "history");
  if (historyCategoryToolbar) historyCategoryToolbar.classList.toggle("hidden", sub !== "history");
  rawFilters.classList.toggle("hidden", sub !== "raw");
  if (rawFiltersExtra) rawFiltersExtra.classList.toggle("hidden", sub !== "raw");
  historyList.classList.toggle("hidden", sub !== "history");
  rawMessageList.classList.toggle("hidden", sub !== "raw");

  if (historyChatLog) historyChatLog.innerHTML = "";
  if (sub === "raw") {
    if (historyChatLabel) historyChatLabel.textContent = "원본 메시지에서 검색";
    if (historyQueryInput)
      historyQueryInput.placeholder = "예: 지난주 슬랙에서 배경 언급한 거 있어?";
  } else {
    if (historyChatLabel) historyChatLabel.textContent = "히스토리에 질문";
    if (historyQueryInput)
      historyQueryInput.placeholder = "예: 배경 관련 피드백 뭐였어?";
  }

  if (sub === "raw") {
    closeHistoryModal();
    selectedHistoryId = null;
    loadRawMessages();
  } else {
    loadHistory();
    updateHistoryStatsLine();
  }
  updateContextPanel();
}

function renderThreadReplyBlocks(container, replies) {
  container.innerHTML = "";
  if (!replies?.length) {
    container.appendChild(el("div", { className: "raw-thread-empty", text: "댓글이 없습니다." }));
    return;
  }
  replies.forEach((r) => {
    const row = el("div", { className: "raw-thread-reply" });
    row.appendChild(
      el("div", {
        className: "raw-thread-reply-meta",
        text: `user ${r.user_id || "—"} · ts ${r.ts || ""}`,
      })
    );
    row.appendChild(el("div", { className: "raw-thread-reply-text", text: r.text || "(내용 없음)" }));
    const thumbs = renderImageThumbnails(r.files || []);
    if (thumbs) {
      const tw = document.createElement("div");
      tw.innerHTML = thumbs;
      row.appendChild(tw);
    }
    if (Array.isArray(r.files) && r.files.length) {
      row.appendChild(el("div", { className: "raw-message-files", html: fileChipListHtml(r.files) }));
    }
    container.appendChild(row);
  });
}

async function expandRawThread(parentTs, threadBody, toggleBtn) {
  const wasOpen = !threadBody.classList.contains("hidden");
  if (wasOpen) {
    threadBody.classList.add("hidden");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
    return;
  }
  threadBody.classList.remove("hidden");
  if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "true");
  if (rawThreadCache[parentTs]) {
    renderThreadReplyBlocks(threadBody, rawThreadCache[parentTs]);
    return;
  }
  threadBody.innerHTML = "";
  threadBody.appendChild(el("div", { className: "raw-thread-loading", text: "불러오는 중…" }));
  try {
    const q = new URLSearchParams();
    q.set("parent_ts", parentTs);
    const replies = await apiJson("GET", `/api/raw-messages/thread?${q.toString()}`, null);
    const list = Array.isArray(replies) ? replies : [];
    rawThreadCache[parentTs] = list;
    renderThreadReplyBlocks(threadBody, list);
  } catch (e) {
    threadBody.innerHTML = "";
    threadBody.appendChild(el("div", { className: "raw-thread-error", text: `불러오기 실패: ${e}` }));
  }
}

function renderRawMessageList() {
  rawMessageList.innerHTML = "";
  if (!rawMessagesCache.length) {
    rawMessageList.appendChild(
      el("div", { className: "history-card", text: "표시할 원본 메시지가 없습니다." })
    );
    return;
  }

  rawMessagesCache.forEach((item) => {
    const wrap = el("div", { className: "raw-message-card-wrap" });
    const card = el("div", { className: "raw-message-card" });
    const full = item.text || "(내용 없음)";
    const preview = full.length > 2000 ? `${full.slice(0, 2000)}…` : full;
    card.appendChild(el("div", { className: "raw-message-text", text: preview }));

    const rawThumbs = renderImageThumbnails(item.files || []);
    if (rawThumbs) {
      const tw = document.createElement("div");
      tw.innerHTML = rawThumbs;
      card.appendChild(tw);
    }

    if (Array.isArray(item.files) && item.files.length) {
      card.appendChild(el("div", { className: "raw-message-files", html: fileChipListHtml(item.files) }));
    }

    const { cls, label } = rawKindBadge(item);
    card.appendChild(el("span", { className: `badge-status ${cls}`, text: label }));

    const uid = item.user_id || "—";
    const ca = slackTsToKST(item.ts) || item.created_at || "";
    card.appendChild(
      el("div", {
        className: "raw-message-meta",
        text: `${ca} · user ${uid} · ts ${item.ts || ""}`,
      })
    );

    card.addEventListener("click", () => {
      if (item.slack_link) window.open(item.slack_link, "_blank", "noopener,noreferrer");
    });

    wrap.appendChild(card);

    const rc = Number(item.reply_count != null ? item.reply_count : 0);
    if (rc > 0) {
      const toggle = el("button", {
        type: "button",
        className: "raw-thread-toggle",
        text: `💬 ${rc}개 댓글`,
      });
      toggle.setAttribute("aria-expanded", "false");
      const threadBody = el("div", { className: "raw-message-thread hidden" });
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        expandRawThread(item.ts, threadBody, toggle);
      });
      wrap.appendChild(toggle);
      wrap.appendChild(threadBody);
    }

    rawMessageList.appendChild(wrap);
  });
}

function debounce(fn, wait) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

const scheduleLoadRawMessages = debounce(() => loadRawMessages(), 300);

async function loadRawMessages() {
  try {
    rawThreadCache = {};
    const q = new URLSearchParams();
    q.set("limit", "100");
    q.set("offset", "0");
    if (rawFilterKind) q.set("kind", rawFilterKind);
    const kw = (rawSearchQuery || "").trim();
    if (kw) q.set("q", kw);
    const au = (rawAuthor || "").trim();
    if (au) q.set("author", au);
    if (rawHasFiles) q.set("has_files", "true");
    q.set("order", rawOrder || "desc");
    const raw = await apiJson("GET", `/api/raw-messages?${q.toString()}`, null);
    rawMessagesCache = Array.isArray(raw) ? raw : [];
    renderRawMessageList();
    updateHistoryStatsLine();
    updateContextPanel();
  } catch (e) {
    rawMessagesCache = [];
    rawMessageList.innerHTML = "";
    rawMessageList.appendChild(el("div", { className: "history-card", text: `불러오기 실패: ${e}` }));
    updateHistoryStatsLine();
    updateContextPanel();
  }
}

function renderHistoryList() {
  historyList.innerHTML = "";
  const filtered = historyRecordsAll;

  if (!filtered.length) {
    historyList.appendChild(el("div", { className: "history-card", text: "표시할 히스토리가 없습니다." }));
    return;
  }

  filtered.forEach((item) => {
    const card = el("div", {
      className: "history-card" + (selectedHistoryId === item.id ? " selected" : ""),
    });
    card.appendChild(el("div", { className: "history-card-topic", text: `#${item.id} ${titleFallback(item)}` }));
    const metaRow = el("div", { className: "history-card-meta-row" });
    metaRow.appendChild(
      el("div", {
        className: "history-card-meta",
        text: `${item.message_time || item.date || ""} · ${item.author_name || item.author_user_id || "—"} · ${item.scope || ""} · ${item.type || ""}`,
      })
    );
    metaRow.appendChild(
      el("span", { className: "badge-category", text: formatCategoryLabel(item.category) })
    );
    card.appendChild(metaRow);
    const badge = el("span", { className: `badge-status ${statusClass(item.status)}`, text: item.status || "—" });
    card.appendChild(badge);

    card.addEventListener("click", () => {
      selectedHistoryId = item.id;
      renderHistoryList();
      openHistoryModal(item);
    });

    historyList.appendChild(card);
  });
}

async function loadHistory() {
  try {
    const q = new URLSearchParams();
    if (historyFilterStatus) q.set("status", historyFilterStatus);
    if (historyCategoryFilter) q.set("category", historyCategoryFilter);
    const qs = q.toString();
    const path = qs ? `/api/history?${qs}` : "/api/history";
    const raw = await apiJson("GET", path, null);
    historyRecordsAll = Array.isArray(raw) ? raw : [];
    renderHistoryList();
    updateContextPanel();
  } catch (e) {
    historyRecordsAll = [];
    historyList.innerHTML = "";
    historyList.appendChild(el("div", { className: "history-card", text: `불러오기 실패: ${e}` }));
    updateContextPanel();
  }
}

historyFilters.querySelectorAll(".filter-pill").forEach((btn) => {
  btn.addEventListener("click", () => {
    historyFilters.querySelectorAll(".filter-pill").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    historyFilterStatus = btn.dataset.status || "";
    selectedHistoryId = null;
    closeHistoryModal();
    loadHistory();
  });
});

if (historyCategoryTabs) {
  historyCategoryTabs.querySelectorAll(".category-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      historyCategoryTabs.querySelectorAll(".category-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      historyCategoryFilter = btn.dataset.category || "";
      selectedHistoryId = null;
      closeHistoryModal();
      loadHistory();
    });
  });
}

historyRefreshBtn.addEventListener("click", () => {
  if (historySubTab === "raw") loadRawMessages();
  else loadHistory();
});

document.querySelectorAll("#view-history .subtab-pill").forEach((btn) => {
  btn.addEventListener("click", () => setHistorySubTab(btn.dataset.subtab));
});

rawFilters.querySelectorAll(".filter-pill").forEach((btn) => {
  btn.addEventListener("click", () => {
    rawFilters.querySelectorAll(".filter-pill").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    rawFilterKind = btn.dataset.rawKind || "";
    loadRawMessages();
  });
});

if (rawSearchInput) {
  rawSearchInput.addEventListener("keyup", () => {
    rawSearchQuery = rawSearchInput.value || "";
    scheduleLoadRawMessages();
  });
}
if (rawAuthorInput) {
  rawAuthorInput.addEventListener("keyup", () => {
    rawAuthor = rawAuthorInput.value || "";
    scheduleLoadRawMessages();
  });
}
if (rawHasFilesInput) {
  rawHasFilesInput.addEventListener("change", () => {
    rawHasFiles = !!rawHasFilesInput.checked;
    loadRawMessages();
  });
}
if (rawOrderSelect) {
  rawOrder = rawOrderSelect.value || "desc";
  rawOrderSelect.addEventListener("change", () => {
    rawOrder = rawOrderSelect.value || "desc";
    loadRawMessages();
  });
}

async function sendHistoryQuery() {
  const message = historyQueryInput.value.trim();
  if (!message) return;

  addBubble(historyChatLog, "user", message);
  historyQueryInput.value = "";
  historyQueryBtn.disabled = true;

  addBubble(historyChatLog, "bot", "응답을 생성 중입니다...", "잠시만 기다려주세요");

  const inspectMode = historySubTab === "raw" ? "원본메시지검색" : "히스토리조회";

  try {
    const payload = { message, mode: inspectMode };
    if (historySubTab === "raw") {
      payload.raw_kind = rawFilterKind || null;
      const rq = (rawSearchQuery || "").trim();
      payload.raw_query = rq || null;
      const ra = (rawAuthor || "").trim();
      payload.raw_author = ra || null;
      if (rawHasFiles) payload.raw_has_files = true;
      payload.raw_order = rawOrder || "desc";
      payload.raw_limit = 100;
    }
    const res = await fetch("/api/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    removeLastBubble(historyChatLog);

    if (!res.ok) {
      const text = await res.text();
      addBubble(historyChatLog, "bot", `요청 실패 (${res.status})\n${text}`);
      return;
    }

    const data = await res.json();
    const meta =
      historySubTab === "raw"
        ? `원문 참조: ${data.rules_checked}건`
        : `rules_checked: ${data.rules_checked}`;
    addBubble(historyChatLog, "bot", formatBotMessage(data.feedback), meta, {
      asHtml: true,
    });
  } catch (e) {
    removeLastBubble(historyChatLog);
    addBubble(historyChatLog, "bot", `에러: ${e}`);
  } finally {
    historyQueryBtn.disabled = false;
  }
}

historyQueryBtn.addEventListener("click", sendHistoryQuery);
historyQueryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendHistoryQuery();
  }
});

// —— Terms ——
function pushRecentTerm(text) {
  const t = text.trim();
  if (!t) return;
  const idx = recentTerms.indexOf(t);
  if (idx >= 0) recentTerms.splice(idx, 1);
  recentTerms.unshift(t);
  while (recentTerms.length > MAX_RECENT_TERMS) recentTerms.pop();
  updateContextPanel();
}

async function sendTerms() {
  const message = termsInput.value.trim();
  if (!message) return;

  pushRecentTerm(message);

  addBubble(termsChatLog, "user", message);
  termsInput.value = "";
  termsSendBtn.disabled = true;

  addBubble(termsChatLog, "bot", "응답을 생성 중입니다...", "잠시만 기다려주세요");

  try {
    const res = await fetch("/api/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        mode: "용어해석",
      }),
    });

    removeLastBubble(termsChatLog);

    if (!res.ok) {
      const text = await res.text();
      addBubble(termsChatLog, "bot", `요청 실패 (${res.status})\n${text}`);
      return;
    }

    const data = await res.json();
    addBubble(termsChatLog, "bot", formatBotMessage(data.feedback), `rules_checked: ${data.rules_checked}`, {
      asHtml: true,
    });
  } catch (e) {
    removeLastBubble(termsChatLog);
    addBubble(termsChatLog, "bot", `에러: ${e}`);
  } finally {
    termsSendBtn.disabled = false;
  }
}

termsSendBtn.addEventListener("click", sendTerms);
termsInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendTerms();
  }
});

// —— Copywriter ——
async function sendCopywriter() {
  const message = (copywriterInput?.value || "").trim();
  if (!message) return;

  addBubble(copywriterChatLog, "user", message);
  copywriterInput.value = "";

  const isSearchOnly = /찾아|검색|어떤.*있|보여줘/.test(message);
  if (isSearchOnly) {
    copywriterSendBtn.disabled = true;
    addBubble(copywriterChatLog, "bot", "카피뱅크에서 검색 중입니다...", "잠시만 기다려주세요");
    try {
      const res = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          mode: "카피창작",
        }),
      });
      await handleCopywriterInspectResult(res, copywriterChatLog, message);
    } catch (e) {
      removeLastBubble(copywriterChatLog);
      addBubble(copywriterChatLog, "bot", `에러: ${e}`);
    } finally {
      copywriterSendBtn.disabled = false;
    }
    return;
  }

  addConditionPickerBubble(copywriterChatLog, message);
}

copywriterSendBtn?.addEventListener("click", sendCopywriter);
copywriterInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendCopywriter();
  }
});

async function submitManualIngest() {
  const text = (manualTextEl?.value || "").trim();
  if (!text) {
    if (manualStatusEl) {
      manualStatusEl.textContent = "본문이 비어있습니다.";
      manualStatusEl.className = "admin-status error";
    }
    return;
  }
  const author = (manualAuthorEl?.value || "").trim();
  const catRaw = (manualCategoryEl?.value || "").trim();

  if (manualSubmitBtn) manualSubmitBtn.disabled = true;
  if (manualStatusEl) {
    manualStatusEl.textContent = "refine 및 적재 중... (문서 로드 시 수 초~수십 초 소요)";
    manualStatusEl.className = "admin-status";
  }
  manualGoHistoryBtn?.classList.add("hidden");

  try {
    const res = await postJsonExpectOk("/api/manual-ingest", {
      text,
      author_name: author || null,
      category: catRaw || null,
    });
    const n = res.doc_link_count || 0;
    if (manualStatusEl) {
      manualStatusEl.textContent =
        `히스토리 적재 완료 (#${res.history_id})` + (n > 0 ? ` · Google 문서 ${n}개 반영` : "");
      manualStatusEl.className = "admin-status";
    }
    if (manualTextEl) manualTextEl.value = "";
    if (manualAuthorEl) manualAuthorEl.value = "";
    if (manualCategoryEl) manualCategoryEl.value = "";
    manualGoHistoryBtn?.classList.remove("hidden");
    if (manualGoHistoryBtn && res.history_id != null) {
      manualGoHistoryBtn.dataset.historyId = String(res.history_id);
    }
  } catch (e) {
    if (e.code === "gdrive_auth_required") {
      if (manualStatusEl) {
        manualStatusEl.textContent = "Google 로그인 후 다시 시도해주세요.";
        manualStatusEl.className = "admin-status";
      }
    } else if (manualStatusEl) {
      manualStatusEl.textContent = `실패: ${e.message}`;
      manualStatusEl.className = "admin-status error";
    }
  } finally {
    if (manualSubmitBtn) manualSubmitBtn.disabled = false;
  }
}

manualSubmitBtn?.addEventListener("click", submitManualIngest);
manualGoHistoryBtn?.addEventListener("click", () => switchView("history"));

// —— Admin (from admin.js) ——
function renderAdminCard(item) {
  const card = el("div", { className: "admin-card" });
  const st = item.status || "대기중";
  if (st === "처리중") {
    card.classList.add("admin-card-processing");
  } else {
    card.addEventListener("click", () => openAdminModal(item));
  }

  card.appendChild(el("div", { className: "admin-card-title", text: `${titleFallback(item)} (#${item.id})` }));
  card.appendChild(
    el("div", {
      className: "admin-card-meta",
      text: `${item.message_time || item.date || ""} · ${item.author_name || item.author_user_id || "—"} · ${item.scope || ""} · ${item.type || ""} · ${formatCategoryLabel(item.category)}`,
    })
  );

  const bodyPreview = item.original_quote || item.summary || "";
  if (bodyPreview) {
    card.appendChild(el("div", { className: "admin-card-body", text: bodyPreview }));
  }

  const cardThumbs = renderImageThumbnails(item.files || []);
  if (cardThumbs) {
    const tw = document.createElement("div");
    tw.innerHTML = cardThumbs;
    card.appendChild(tw);
  }

  if (Array.isArray(item.files) && item.files.length) {
    card.appendChild(el("div", { className: "admin-card-files", html: fileChipListHtml(item.files) }));
  }

  if (Number(item.has_conflict) === 1) {
    card.appendChild(
      el("div", {
        className: "admin-warn",
        text: `충돌: ${item.conflict_explanation || ""}`,
      })
    );
  }

  card.appendChild(
    el("span", { className: `badge-status ${approvalStatusBadgeClass(st)}`, text: st })
  );

  return card;
}

async function loadAdmin({ append = false } = {}) {
  try {
    if (!append) {
      adminOffset = 0;
      adminListCache = [];
      if (adminCardsSlack) adminCardsSlack.innerHTML = "";
      if (adminCardsFigma) adminCardsFigma.innerHTML = "";
    }
    if (adminStatus) adminStatus.textContent = "불러오는 중...";
    const q = new URLSearchParams();
    q.set("limit", String(ADMIN_LIMIT));
    q.set("offset", String(adminOffset));
    if (adminStatusFilter) q.set("status", adminStatusFilter);
    if (adminSearch.trim()) q.set("q", adminSearch.trim());
    if (adminAuthor.trim()) q.set("author", adminAuthor.trim());
    q.set("order", adminOrder);

    const res = await apiJson("GET", `/api/approvals?${q.toString()}`, null);
    const items = Array.isArray(res?.items)
      ? res.items
      : Array.isArray(res)
        ? res
        : [];
    adminTotal = typeof res?.total === "number" ? res.total : items.length;
    adminHasMore = !!res?.has_more;
    adminListCache = append ? adminListCache.concat(items) : items;

    if (append) {
      appendAdminColumns(items);
    } else {
      renderAdminColumns(adminListCache);
    }

    adminOffset += items.length;

    if (adminLoadMoreBtn) {
      adminLoadMoreBtn.classList.toggle("hidden", !adminHasMore);
    }

    const nWait = adminListCache.filter((x) => (x.status || "") === "대기중").length;
    const nProc = adminListCache.filter((x) => (x.status || "") === "처리중").length;
    if (adminStatus) {
      adminStatus.textContent =
        nProc > 0
          ? `총 ${adminTotal}건 · 표시 ${adminListCache.length}건 (대기 ${nWait} · 처리중 ${nProc})`
          : `총 ${adminTotal}건 · 표시 ${adminListCache.length}건 (대기 ${nWait})`;
    }
    updateContextPanel();
  } catch (e) {
    if (adminStatus) adminStatus.textContent = `에러: ${e.message}`;
    adminListCache = [];
    adminTotal = 0;
    adminOffset = 0;
    if (adminLoadMoreBtn) adminLoadMoreBtn.classList.add("hidden");
    updateContextPanel();
  }
}

if (adminRefreshBtn) adminRefreshBtn.addEventListener("click", () => loadAdmin({ append: false }));

const scheduleAdminLoad = debounce(() => loadAdmin({ append: false }), 300);

if (adminSearchInput) {
  adminSearchInput.addEventListener("keyup", () => {
    adminSearch = adminSearchInput.value || "";
    scheduleAdminLoad();
  });
}
if (adminAuthorInput) {
  adminAuthorInput.addEventListener("keyup", () => {
    adminAuthor = adminAuthorInput.value || "";
    scheduleAdminLoad();
  });
}
if (adminStatusFilters) {
  adminStatusFilters.querySelectorAll(".filter-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      adminStatusFilters.querySelectorAll(".filter-pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      adminStatusFilter = btn.getAttribute("data-status") ?? "";
      loadAdmin({ append: false });
    });
  });
}
if (adminOrderSelect) {
  adminOrder = adminOrderSelect.value || "desc";
  adminOrderSelect.addEventListener("change", () => {
    adminOrder = adminOrderSelect.value || "desc";
    loadAdmin({ append: false });
  });
}
if (adminLoadMoreBtn) {
  adminLoadMoreBtn.addEventListener("click", () => loadAdmin({ append: true }));
}

// —— Boot ——
(async function bootApp() {
  const qs = new URLSearchParams(window.location.search || "");
  const isDeepLink =
    qs.has("gdrive_inspection_id") || qs.has("figma_inspection_id") || qs.has("inspection");

  if (isDeepLink) {
    // 딥링크(Teams 카드 등)로 들어온 경우: 로그인 게이트를 스킵하고 결과만 노출
    document.body.classList.add("auth-authenticated");
  } else {
    await checkGdriveAuthStatus();
  }
  addBubble(
    chatLog,
    "bot",
    formatBotMessage(
      "안녕하세요! 올더뮤 검수봇입니다.\n사이드바에서 뷰를 바꾸거나 **+ New Inspection**으로 새 검수를 시작하세요.\n드라이브 폴더 URL은 입력창에 붙여 넣거나, 로컬 이미지를 첨부하세요.\nEnter 전송 · Shift+Enter 줄바꿈"
    ),
    "",
    { asHtml: true }
  );
  updateContextPanel();

  // Teams 카드의 "검수 결과 보기" 딥링크 지원
  try {
    const insId = (qs.get("gdrive_inspection_id") || "").trim();
    if (insId) {
      const r = await fetch(`/api/gdrive/inspections/${encodeURIComponent(insId)}`);
      if (r.ok) {
        const ins = await r.json();
        const rawList = ins.images || [];
        const driveImgList = rawList.some((x) => x.kind) ? rawList.filter((x) => !x.kind || x.kind === "image") : rawList;
        const meta = `files: ${ins.file_count ?? "?"} · rules_checked: ${ins.rules_checked ?? "?"}`;
        const beforeHtml = formatBotMessage(ins.feedback || "");
        let html = insertInlineImages(beforeHtml, driveImgList, ins.id, null, null);
        const imgOnly = driveImgList.length;
        // 이미지가 1장이고 헤딩이 없으면 치환이 안 될 수 있음 → 버블 상단에 직접 삽입
        if (imgOnly > 0 && html === beforeHtml) {
          const imgTags = Array.from(
            { length: Math.min(imgOnly, 10) },
            (_, i) =>
              `<img src="/api/gdrive/inspection-image/${encodeURIComponent(String(ins.id))}/${i}" class="inline-review-img" loading="lazy" alt="">`
          ).join("");
          html = imgTags + "<br>" + html;
        }
        addBubble(chatLog, "bot", html, meta, { asHtml: true });
      }
    }
    const slackIns = (qs.get("inspection") || "").trim();
    if (slackIns) {
      const r2 = await fetch(`/api/slack-inspections/${encodeURIComponent(slackIns)}`);
      if (r2.ok) {
        const ins = await r2.json();
        const n = Number(ins.file_count || 0);
        const fakeImages = Array.from({ length: Math.min(n, 10) }, () => ({ id: "" }));
        const meta = `슬랙 피드백 검수 · rules_checked: ${ins.rules_checked ?? "?"}`;
        const beforeHtml = formatBotMessage(ins.feedback || "");
        let html = insertInlineImages(beforeHtml, fakeImages, null, ins.id, null);
        // 이미지가 1장이고 헤딩이 없으면 치환이 안 될 수 있음 → 버블 상단에 직접 삽입
        if (n > 0 && html === beforeHtml) {
          const imgTags = Array.from(
            { length: Math.min(n, 10) },
            (_, i) =>
              `<img src="/api/slack-inspection-image/${encodeURIComponent(String(ins.id))}/${i}" class="inline-review-img" loading="lazy" alt="">`
          ).join("");
          html = imgTags + "<br>" + html;
        }
        // 광고주 원문 버블 먼저 표시
        if ((ins.original_text || "").trim()) {
          addBubble(chatLog, "user", ins.original_text, "광고주 원문");
        }
        addBubble(chatLog, "bot", html, meta, { asHtml: true });
      }
    }
    const figmaIns = (qs.get("figma_inspection_id") || "").trim();
    if (figmaIns) {
      const r3 = await fetch(`/api/figma/inspections/${encodeURIComponent(figmaIns)}`);
      if (r3.ok) {
        const ins = await r3.json();
        const n = Math.min(Number(ins.file_count || 0), 10);
        const fakeImages = Array.from({ length: n }, () => ({ id: ins.file_key || "figma" }));
        const meta = `Figma 검수 · rules_checked: ${ins.rules_checked ?? "?"}`;
        const beforeHtml = formatBotMessage(ins.feedback || "");
        let html = insertInlineImages(
          beforeHtml,
          fakeImages,
          null,
          null,
          ins.id
        );
        // 이미지가 1장이고 헤딩이 없으면 치환이 안 될 수 있음 → 버블 상단에 직접 삽입
        if (n > 0 && html === beforeHtml) {
          const imgTags = Array.from(
            { length: n },
            (_, i) =>
              `<img src="/api/figma/inspection-image/${encodeURIComponent(String(ins.id))}/${i}" class="inline-review-img" loading="lazy" alt="">`
          ).join("");
          html = imgTags + "<br>" + html;
        }
        addBubble(chatLog, "bot", html, meta, { asHtml: true });
      }
    }
  } catch {
    // ignore
  }
})();

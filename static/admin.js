const cards = document.getElementById("cards");
const refreshBtn = document.getElementById("refreshBtn");
const statusEl = document.getElementById("status");

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === "className") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  });
  children.forEach((c) => node.appendChild(c));
  return node;
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  return res.json();
}

function renderCard(item) {
  const tt =
    String(item.topic || "").trim() ||
    String(item.full_text || "")
      .trim()
      .split("\n")[0]
      .slice(0, 80) ||
    "(제목 없음)";
  const title = el("div", { className: "brand-title", text: `${tt} (#${item.id})` });
  title.style.fontSize = "16px";

  const meta = el("div", { className: "brand-sub", text: `${item.date} · scope=${item.scope} · type=${item.type}` });
  meta.style.marginTop = "6px";

  const quote = el("div", { className: "bubble bot", text: item.original_quote || item.summary });
  quote.style.maxWidth = "100%";

  const row = el("div");
  row.style.display = "flex";
  row.style.flexWrap = "wrap";
  row.style.gap = "8px";
  row.style.marginTop = "10px";

  const approve = el("button", { className: "send-btn", text: "승인(적재)" });
  approve.style.padding = "10px 12px";
  approve.addEventListener("click", async () => {
    statusEl.textContent = "처리 중...";
    await api("POST", `/api/approvals/${item.id}/approve`, {});
    await refresh();
  });

  const reject = el("button", { className: "mode-btn", text: "폐기" });
  reject.addEventListener("click", async () => {
    statusEl.textContent = "처리 중...";
    await api("POST", `/api/approvals/${item.id}/reject`, {});
    await refresh();
  });

  row.appendChild(approve);
  row.appendChild(reject);

  if (Number(item.has_conflict) === 1) {
    const warn = el("div", { className: "bubble bot", text: `⚠️ 충돌 감지\n${item.conflict_explanation || ""}` });
    warn.style.maxWidth = "100%";
    warn.style.borderColor = "rgba(245,158,11,0.35)";
    warn.style.background = "rgba(245,158,11,0.08)";

    const useNew = el("button", { className: "send-btn", text: "신규로 교체" });
    useNew.style.padding = "10px 12px";
    useNew.addEventListener("click", async () => {
      statusEl.textContent = "처리 중...";
      await api("POST", `/api/approvals/${item.id}/conflict`, { action: "use_new" });
      await refresh();
    });

    const keepOld = el("button", { className: "mode-btn", text: "기존 유지" });
    keepOld.addEventListener("click", async () => {
      statusEl.textContent = "처리 중...";
      await api("POST", `/api/approvals/${item.id}/conflict`, { action: "keep_old" });
      await refresh();
    });

    const keepBoth = el("button", { className: "mode-btn", text: "둘 다 병기" });
    keepBoth.addEventListener("click", async () => {
      statusEl.textContent = "처리 중...";
      await api("POST", `/api/approvals/${item.id}/conflict`, { action: "keep_both" });
      await refresh();
    });

    row.appendChild(useNew);
    row.appendChild(keepOld);
    row.appendChild(keepBoth);

    const card = el("div", { className: "bubble bot" }, [title, meta, warn, quote, row]);
    card.style.maxWidth = "100%";
    return card;
  }

  const card = el("div", { className: "bubble bot" }, [title, meta, quote, row]);
  card.style.maxWidth = "100%";
  return card;
}

async function refresh() {
  try {
    statusEl.textContent = "불러오는 중...";
    const res = await api("GET", "/api/approvals?limit=100&offset=0", null);
    const list = Array.isArray(res?.items) ? res.items : Array.isArray(res) ? res : [];
    const total = res.total ?? list.length;
    cards.innerHTML = "";
    if (!list.length) {
      cards.appendChild(el("div", { className: "bubble bot", text: "대기중인 항목이 없습니다." }));
    } else {
      list.forEach((item) => cards.appendChild(renderCard(item)));
    }
    statusEl.textContent = `대기 ${total}건 (첫 ${list.length}건 표시) — 자세한 관리는 메인 앱의 '슬랙 승인 대기' 탭을 이용하세요.`;
  } catch (e) {
    statusEl.textContent = `에러: ${e.message}`;
  }
}

refreshBtn.addEventListener("click", refresh);

refresh();
setInterval(refresh, 30000);


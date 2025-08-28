/// <reference path="./types/telegram-webapp.d.ts" />

type CoachType = "human" | "ai_coach";

type ProgramResp = {
  program?: string;
  created_at?: number | string;
  coach_type?: CoachType;
  error?: string;
};

type HistoryItem = {
  id: number;
  created_at: number;
  coach_type: CoachType;
};

type HistoryResp = {
  programs?: HistoryItem[];
  error?: string;
};

type SubscriptionResp = {
  program?: string;
  error?: string;
};

const tg = window?.Telegram?.WebApp;
const initData: string = tg?.initData || "";

const content = document.getElementById("content");
const dateEl = document.getElementById("program-date");
const originEl = document.getElementById("program-origin");
const controls = document.getElementById("controls");

const API = {
  program: "/webapp/api/program/",
  programs: "/webapp/api/programs/",
  subscription: "/webapp/api/subscription/",
} as const;

function setText(txt: string): void {
  if (content) content.textContent = txt;
}

function formatDate(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString();
}

function statusToMessage(status: number): string {
  if (status === 403) return "Unauthorized";
  if (status === 404) return "Not found";
  if (status >= 500 || status === 0) return "Server error";
  return "Unexpected error";
}

let inflight: AbortController | null = null;

async function getJSON<T>(url: string): Promise<{ ok: true; data: T } | { ok: false; status: number }> {
  if (inflight) inflight.abort();
  inflight = new AbortController();
  try {
    const resp = await fetch(url, { signal: inflight.signal });
    if (!resp.ok) return { ok: false, status: resp.status };
    const data = (await resp.json()) as T;
    return { ok: true, data };
  } catch (e: unknown) {
    if ((e as any)?.name === "AbortError") return { ok: false, status: 0 };
    console.error("Fetch failed", e);
    return { ok: false, status: 500 };
  } finally {
    inflight = null;
  }
}

function renderProgramControls(): void {
  if (!controls) return;
  controls.innerHTML = "";

  const btn = document.createElement("button");
  btn.textContent = "History";
  btn.addEventListener("click", () => {
    const url = new URL(window.location.toString());
    url.searchParams.set("page", "history");
    url.searchParams.delete("program_id");
    url.searchParams.delete("type");
    window.history.pushState({}, "", url);
    void loadHistory();
  });

  controls.appendChild(btn);
}

async function loadProgram(programId?: string | null): Promise<void> {
  let message: string | null = null;

  const q = new URLSearchParams();
  q.set("init_data", initData);
  if (programId) q.set("program_id", programId);

  const url = `${API.program}?${q.toString()}`;
  const res = await getJSON<ProgramResp>(url);

  if ("status" in res) {
    message = statusToMessage(res.status);
  } else {
    const data = res.data;
    if (data.error === "service_unavailable") {
      message = "Service temporarily unavailable";
    } else {
      if (dateEl) {
        const ts = Number(data.created_at);
        dateEl.textContent = Number.isFinite(ts) ? `Created: ${formatDate(ts)}` : "";
      }
      if (originEl) {
        if (data.coach_type === "ai_coach") {
          originEl.textContent = "AI";
          originEl.className = "ai-label";
        } else {
          originEl.textContent = "";
          originEl.className = "";
        }
      }
      setText(data.program || "");
    }
  }

  if (message) {
    setText(message);
    if (dateEl) dateEl.textContent = "";
    if (originEl) {
      originEl.textContent = "";
      originEl.className = "";
    }
  }

  renderProgramControls();

  const next = new URL(window.location.toString());
  next.searchParams.delete("page");
  if (programId && !message) {
    next.searchParams.set("program_id", programId);
  } else {
    next.searchParams.delete("program_id");
  }
  next.searchParams.delete("type");
  window.history.replaceState({}, "", next);
}

async function loadHistory(): Promise<void> {
  if (dateEl) dateEl.textContent = "";
  if (originEl) {
    originEl.textContent = "";
    originEl.className = "";
  }

  const q = new URLSearchParams();
  q.set("init_data", initData);
  const url = `${API.programs}?${q.toString()}`;
  const res = await getJSON<HistoryResp>(url);

  if ("status" in res) {
    setText(statusToMessage(res.status));
    return;
  }

  const data = res.data;
  if (data.error === "service_unavailable") {
    setText("Service temporarily unavailable");
    return;
  }
  if (!data.programs || data.programs.length === 0) {
    setText("No programs found");
    return;
  }
  if (!content) return;

  content.innerHTML = "";
  const list = document.createElement("ul");
  list.className = "history-list";

  let sortBy: "date" | "origin" = "date";
  let asc = false;

  function render(): void {
    list.innerHTML = "";
    const items = [...data.programs!];
    items.sort((a, b) => {
      if (sortBy === "origin") {
        const av = a.coach_type === "ai_coach" ? 1 : 0;
        const bv = b.coach_type === "ai_coach" ? 1 : 0;
        return asc ? av - bv : bv - av;
      }
      return asc ? a.created_at - b.created_at : b.created_at - a.created_at;
    });

    for (const p of items) {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.textContent = formatDate(p.created_at);
      link.href = "#";
      link.addEventListener("click", (e) => {
        e.preventDefault();
        const url = new URL(window.location.toString());
        url.searchParams.delete("page");
        url.searchParams.set("program_id", String(p.id));
        url.searchParams.delete("type");
        window.history.pushState({}, "", url);
        void loadProgram(String(p.id));
      });
      li.appendChild(link);

      if (p.coach_type === "ai_coach") {
        const badge = document.createElement("span");
        badge.textContent = " AI";
        badge.className = "ai-label";
        li.appendChild(badge);
      }
      list.appendChild(li);
    }
  }

  render();
  content.appendChild(list);

  if (controls) {
    controls.innerHTML = "";
    const orderBtn = document.createElement("button");
    const modeBtn = document.createElement("button");

    function updateButtons(): void {
      modeBtn.textContent = sortBy === "date" ? "Sort by: Date" : "Sort by: Origin";
      if (sortBy === "date") {
        orderBtn.textContent = asc ? "Order: Oldest" : "Order: Newest";
      } else {
        orderBtn.textContent = asc ? "Order: Human First" : "Order: AI First";
      }
    }

    orderBtn.addEventListener("click", () => {
      asc = !asc;
      updateButtons();
      render();
    });
    modeBtn.addEventListener("click", () => {
      sortBy = sortBy === "date" ? "origin" : "date";
      updateButtons();
      render();
    });

    updateButtons();
    controls.appendChild(modeBtn);
    controls.appendChild(orderBtn);
  }
}

async function loadSubscription(): Promise<void> {
  let message: string | null = null;

  if (dateEl) dateEl.textContent = "";
  if (originEl) {
    originEl.textContent = "";
    originEl.className = "";
  }

  const q = new URLSearchParams();
  q.set("init_data", initData);
  const url = `${API.subscription}?${q.toString()}`;
  const res = await getJSON<SubscriptionResp>(url);

  if ("status" in res) {
    message = statusToMessage(res.status);
  } else {
    const data = res.data;
    if (data.error === "service_unavailable") {
      message = "Service temporarily unavailable";
    } else {
      setText(data.program || "");
    }
  }

  if (message) setText(message);

  renderProgramControls();

  const next = new URL(window.location.toString());
  next.searchParams.set("type", "subscription");
  window.history.replaceState({}, "", next);
}

function routeFromLocation(): void {
  const params = new URLSearchParams(window.location.search);
  const type = params.get("type");
  const page = params.get("page") ?? "program";

  if (type === "subscription") {
    void loadSubscription();
  } else if (page === "history") {
    void loadHistory();
  } else {
    const programId = params.get("program_id");
    void loadProgram(programId);
  }
}

if (!initData) {
  setText("Open this page from Telegram.");
  console.error("No Telegram WebApp context: Telegram.WebApp.initData is empty.");
} else {
  try {
    tg?.ready?.();
  } catch {}
  routeFromLocation();
  window.addEventListener("popstate", routeFromLocation);
}

const tg: { initData?: string } | undefined = (window as any)?.Telegram?.WebApp;

const initData: string = tg?.initData || "";
const content = document.getElementById("content");
const dateEl = document.getElementById("program-date");
const originEl = document.getElementById("program-origin");
const controls = document.getElementById("controls");

function setText(txt: string): void {
  if (content) {
    content.textContent = txt;
  }
}

function formatDate(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString();
}

type CoachType = "human" | "ai_coach";

function renderProgramControls(): void {
  if (!controls) return;
  controls.innerHTML = "";
  const btn = document.createElement("button");
  btn.textContent = "History";
  btn.addEventListener("click", () => {
    const url = new URL(window.location.toString());
    url.searchParams.set("page", "history");
    url.searchParams.delete("program_id");
    window.history.pushState({}, "", url);
    void loadHistory();
  });
  controls.appendChild(btn);
}

async function loadProgram(programId?: string | null): Promise<void> {
  let message: string | null = null;
  try {
    const q = new URLSearchParams();
    q.set("init_data", initData);
    if (programId) q.set("program_id", programId);
    const resp = await fetch(`/webapp/api/program/?${q.toString()}`);
    if (resp.status === 403) {
      message = "Unauthorized";
    } else if (resp.status === 404) {
      message = "No program found";
    } else if (resp.status >= 500) {
      message = "Server error";
    } else {
      const data: { program?: string; created_at?: number | string; coach_type?: CoachType; error?: string } =
        await resp.json();
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
  } catch (err) {
    console.error("Failed to load program", err);
    message = "Server error";
  } finally {
    if (message) {
      setText(message);
      if (dateEl) dateEl.textContent = "";
      if (originEl) {
        originEl.textContent = "";
        originEl.className = "";
      }
    }
    renderProgramControls();
    const url = new URL(window.location.toString());
    url.searchParams.delete("page");
    if (programId && !message) {
      url.searchParams.set("program_id", programId);
    } else {
      url.searchParams.delete("program_id");
    }
    window.history.replaceState({}, "", url);
  }
}

interface HistoryItem {
  id: number;
  created_at: number;
  coach_type: CoachType;
}

async function loadHistory(): Promise<void> {
  try {
    if (dateEl) dateEl.textContent = "";
    if (originEl) {
      originEl.textContent = "";
      originEl.className = "";
    }
    const q = new URLSearchParams();
    q.set("init_data", initData);
    const resp = await fetch(`/webapp/api/programs/?${q.toString()}`);
    if (resp.status === 403) {
      setText("Unauthorized");
      return;
    }
    if (resp.status === 404) {
      setText("No programs found");
      return;
    }
    if (resp.status >= 500) {
      setText("Server error");
      return;
    }
    const data: { programs?: HistoryItem[]; error?: string } = await resp.json();
    if (data.error === "service_unavailable") {
      setText("Service temporarily unavailable");
      return;
    }
    if (!data.programs) {
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
      const items = [...data.programs];
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
  } catch (err) {
    console.error("Failed to load history", err);
    setText("Server error");
  }
}

if (!initData) {
  setText("Open this page from Telegram.");
  console.error("No Telegram WebApp context: Telegram.WebApp.initData is empty.");
} else {
  const params = new URLSearchParams(window.location.search);
  const page = params.get("page") ?? "program";
  if (page === "history") {
    void loadHistory();
  } else {
    const programId = params.get("program_id");
    void loadProgram(programId);
  }
  window.addEventListener("popstate", () => {
    const p = new URLSearchParams(window.location.search);
    const view = p.get("page") ?? "program";
    if (view === "history") {
      void loadHistory();
    } else {
      void loadProgram(p.get("program_id"));
    }
  });
}

const tg: { initData?: string } | undefined = (window as any)?.Telegram?.WebApp;

const initData: string = tg?.initData || "";
const content = document.getElementById("content");
const dateEl = document.getElementById("program-date");
const controls = document.getElementById("controls");

function setText(txt: string): void {
  if (content) {
    content.textContent = txt;
    (content as HTMLElement).style.whiteSpace = "pre-wrap";
  }
}

function formatDate(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString();
}

function goToHistory(): void {
  const q = new URLSearchParams();
  q.set("page", "history");
  window.location.search = q.toString();
}

async function loadProgram(programId?: string | null): Promise<void> {
  try {
    const q = new URLSearchParams();
    q.set("init_data", initData);
    if (programId) q.set("program_id", programId);
    const resp = await fetch(`/webapp/api/program/?${q.toString()}`);
    if (resp.status === 403) {
      setText("Unauthorized");
      return;
    }
    if (resp.status === 404) {
      setText("No program found");
      return;
    }
    if (resp.status >= 500) {
      setText("Server error");
      return;
    }
    const data: { program: string; created_at: number } = await resp.json();
    if (dateEl) dateEl.textContent = formatDate(data.created_at);
    setText(data.program);
    if (controls) {
      const btn = document.createElement("button");
      btn.textContent = "History";
      btn.addEventListener("click", goToHistory);
      controls.appendChild(btn);
    }
  } catch (err) {
    console.error("Failed to load program", err);
    setText("Server error");
  }
}

async function loadHistory(): Promise<void> {
  try {
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
    const data: { programs: { id: number; created_at: number }[] } = await resp.json();
    if (!content) return;
    content.innerHTML = "";
    const list = document.createElement("ul");
    let asc = false;
    function render(): void {
      list.innerHTML = "";
      const items = [...data.programs];
      items.sort((a, b) => (asc ? a.created_at - b.created_at : b.created_at - a.created_at));
      for (const p of items) {
        const li = document.createElement("li");
        const link = document.createElement("a");
        link.textContent = formatDate(p.created_at);
        link.href = `?program_id=${p.id}`;
        li.appendChild(link);
        list.appendChild(li);
      }
    }
    render();
    content.appendChild(list);
    if (controls) {
      controls.innerHTML = "";
      const sortBtn = document.createElement("button");
      sortBtn.textContent = "Sort: Newest";
      sortBtn.addEventListener("click", () => {
        asc = !asc;
        sortBtn.textContent = asc ? "Sort: Oldest" : "Sort: Newest";
        render();
      });
      controls.appendChild(sortBtn);
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
}

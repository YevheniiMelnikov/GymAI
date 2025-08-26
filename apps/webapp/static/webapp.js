var _a, _b;
const tg = (_a = window === null || window === void 0 ? void 0 : window.Telegram) === null || _a === void 0 ? void 0 : _a.WebApp;
const initData = (tg === null || tg === void 0 ? void 0 : tg.initData) || "";
const content = document.getElementById("content");
const dateEl = document.getElementById("program-date");
const controls = document.getElementById("controls");
function setText(txt) {
    if (content) {
        content.textContent = txt;
        content.style.whiteSpace = "pre-wrap";
    }
}
function formatDate(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString();
}
function goToHistory() {
    const q = new URLSearchParams();
    q.set("page", "history");
    window.location.search = q.toString();
}
async function loadProgram(programId) {
    try {
        const q = new URLSearchParams();
        q.set("init_data", initData);
        if (programId)
            q.set("program_id", programId);
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
        const data = await resp.json();
        if (dateEl)
            dateEl.textContent = formatDate(data.created_at);
        setText(data.program);
        if (controls) {
            const btn = document.createElement("button");
            btn.textContent = "History";
            btn.addEventListener("click", goToHistory);
            controls.appendChild(btn);
        }
    }
    catch (err) {
        console.error("Failed to load program", err);
        setText("Server error");
    }
}
async function loadHistory() {
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
        const data = await resp.json();
        if (!content)
            return;
        content.innerHTML = "";
        const list = document.createElement("ul");
        let asc = false;
        function render() {
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
    }
    catch (err) {
        console.error("Failed to load history", err);
        setText("Server error");
    }
}
if (!initData) {
    setText("Open this page from Telegram.");
    console.error("No Telegram WebApp context: Telegram.WebApp.initData is empty.");
}
else {
    const params = new URLSearchParams(window.location.search);
    const page = (_b = params.get("page")) !== null && _b !== void 0 ? _b : "program";
    if (page === "history") {
        void loadHistory();
    }
    else {
        const programId = params.get("program_id");
        void loadProgram(programId);
    }
}

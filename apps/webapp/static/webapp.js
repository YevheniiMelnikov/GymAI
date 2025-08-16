var _a, _b;
const tg = (_a = window === null || window === void 0 ? void 0 : window.Telegram) === null || _a === void 0 ? void 0 : _a.WebApp;
const params = new URLSearchParams(window.location.search);
const type = (_b = params.get("type")) !== null && _b !== void 0 ? _b : "program";
const endpoint = type === "subscription" ? "/webapp/api/subscription/" : "/webapp/api/program/";
const initData = (tg === null || tg === void 0 ? void 0 : tg.initData) || params.get("init_data") || "";
async function loadProgram() {
    var _a;
    const content = document.getElementById("content");
    if (!content) {
        return;
    }
    try {
        const response = await fetch(`${endpoint}?init_data=${encodeURIComponent(initData)}`);
        if (response.status === 403) {
            content.innerText = "Unauthorized";
            return;
        }
        if (response.status === 404) {
            content.innerText = "No program found";
            return;
        }
        if (response.status >= 500) {
            content.innerText = "Server error";
            return;
        }
        const data = await response.json();
        content.innerText = (_a = data.program) !== null && _a !== void 0 ? _a : "";
    }
    catch (_b) {
        content.innerText = "Server error";
    }
}
void loadProgram();

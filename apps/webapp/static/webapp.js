var _a;
const tg = window.Telegram.WebApp;
const params = new URLSearchParams(window.location.search);
const type = (_a = params.get("type")) !== null && _a !== void 0 ? _a : "program";
const endpoint = type === "subscription" ? "/webapp/api/subscription/" : "/webapp/api/program/";
async function loadProgram() {
    var _a;
    const content = document.getElementById("content");
    if (!content) {
        return;
    }
    try {
        const response = await fetch(`${endpoint}?init_data=${encodeURIComponent(tg.initData)}`);
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

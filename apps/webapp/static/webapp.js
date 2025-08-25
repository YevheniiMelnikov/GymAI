/* static/webapp/webapp.js */
(function () {
  const tg = (typeof window !== "undefined" && window.Telegram && window.Telegram.WebApp) || undefined;

  // Только реальный Telegram WebApp. Без него — не работаем.
  const initData = tg?.initData || "";
  const content = document.getElementById("content");

  function setText(txt) {
    if (content) content.innerText = txt;
  }

  if (!initData) {
    setText("Open this page from Telegram.");
    console.error("No Telegram WebApp context: Telegram.WebApp.initData is empty.");
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const type = params.get("type") ?? "program";
  const endpoint = type === "subscription" ? "/webapp/api/subscription/" : "/webapp/api/program/";

  (async function loadProgram() {
    try {
      const q = new URLSearchParams();
      // НИКАКОГО params.get('init_data') и никакого encodeURIComponent(initData)
      q.set("init_data", initData);

      console.log("endpoint=", endpoint, "initData.len=", initData.length);
      const response = await fetch(`${endpoint}?${q.toString()}`);
      console.log("response.status=", response.status);

      if (response.status === 403) {
        const body = await response.text();
        console.error("Unauthorized response", body);
        setText("Unauthorized");
        return;
      }
      if (response.status === 404) {
        setText("No program found");
        return;
      }
      if (response.status >= 500) {
        const body = await response.text();
        console.error("Server error", body);
        setText("Server error");
        return;
      }
      const data = await response.json();
      setText(data.program ?? "");
    } catch (err) {
      console.error("Failed to load program", err);
      setText("Server error");
    }
  })();
})();

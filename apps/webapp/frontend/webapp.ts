const tg: { initData?: string } | undefined = (window as any)?.Telegram?.WebApp;
const params: URLSearchParams = new URLSearchParams(window.location.search);
const type: string = params.get("type") ?? "program";
const endpoint: string =
  type === "subscription" ? "/webapp/api/subscription/" : "/webapp/api/program/";
const initData: string = tg?.initData || params.get("init_data") || "";

async function loadProgram(): Promise<void> {
  const content: HTMLElement | null = document.getElementById("content");
  if (!content) {
    return;
  }
  try {
    console.log("endpoint=", endpoint, "initData.len=", initData.length);
    const response: Response = await fetch(
      `${endpoint}?init_data=${encodeURIComponent(initData)}`,
    );
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
    const data: { program?: string } = await response.json();
    content.innerText = data.program ?? "";
  } catch {
    content.innerText = "Server error";
  }
}

void loadProgram();

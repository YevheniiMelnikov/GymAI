const tg: { initData: string } = (window as any).Telegram.WebApp;
const params: URLSearchParams = new URLSearchParams(window.location.search);
const type: string = params.get("type") ?? "program";
const endpoint: string =
  type === "subscription" ? "/webapp/api/subscription/" : "/webapp/api/program/";

async function loadProgram(): Promise<void> {
  const content: HTMLElement | null = document.getElementById("content");
  if (!content) {
    return;
  }
  try {
    const response: Response = await fetch(
      `${endpoint}?init_data=${encodeURIComponent(tg.initData)}`,
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

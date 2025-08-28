/// <reference path="./types/telegram-webapp.d.ts" />

// Language mapping and i18n loader
// Accept legacy values we may get from backend: eng, ru, ua, en, ru, uk

type CoachType = 'human' | 'ai_coach';
type LangCode = 'en' | 'ru' | 'uk';
const LANG_MAP: Record<string, LangCode> = { eng: 'en', en: 'en', ru: 'ru', ua: 'uk', uk: 'uk' };

let messages: Record<string, string> = {};
const fallbackEn: Record<string, string> = {
  history: 'History',
  created: 'Created',
  ai_label: 'AI',
  service_unavailable: 'Service temporarily unavailable',
  unauthorized: 'Unauthorized',
  not_found: 'Not found',
  server_error: 'Server error',
  unexpected_error: 'Unexpected error',
  no_programs: 'No programs found',
  sort_newest: 'Sort: Newest',
  sort_oldest: 'Sort: Oldest',
  show_ai: 'Show AI workout plans',
  open_from_telegram: 'Open this page from Telegram.'
};

async function loadMessages(code: LangCode): Promise<void> {
  const base = (window as any).__STATIC_PREFIX__ || '/static/';
  try {
    const res = await fetch(`${base}i18n/${code}.json`, { cache: 'no-store' });
    messages = res.ok ? await res.json() : fallbackEn;
  } catch {
    messages = fallbackEn;
  }
}

function t<K extends keyof typeof fallbackEn>(key: K): string {
  return (messages[key] ?? fallbackEn[key]) as string;
}

async function applyLang(raw: string | undefined): Promise<LangCode> {
  const code: LangCode = LANG_MAP[raw ?? ''] ?? 'en';
  document.documentElement.lang = code;
  await loadMessages(code);
  return code;
}

function formatDate(ts: number, locale: string): string {
  return new Date(ts * 1000).toLocaleDateString(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  });
}

type ProgramResp = {
  program?: string;
  created_at?: number | string;
  coach_type?: CoachType;
  error?: string;
  language?: string;
};

type HistoryItem = { id: number; created_at: number; coach_type: CoachType };

type HistoryResp = {
  programs?: HistoryItem[];
  error?: string;
  language?: string;
};

type SubscriptionResp = {
  program?: string;
  error?: string;
  language?: string;
};

const tg = window?.Telegram?.WebApp;
const initData: string = tg?.initData || '';

const content = document.getElementById('content');
const dateEl = document.getElementById('program-date');
const originEl = document.getElementById('program-origin');
const controls = document.getElementById('controls');

const API = {
  program: '/webapp/api/program/',
  programs: '/webapp/api/programs/',
  subscription: '/webapp/api/subscription/'
} as const;

function setText(txt: string): void {
  if (content) content.textContent = txt;
}

function statusToMessage(status: number): string {
  if (status === 403) return t('unauthorized');
  if (status === 404) return t('not_found');
  if (status >= 500 || status === 0) return t('server_error');
  return t('unexpected_error');
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
    if ((e as any)?.name === 'AbortError') return { ok: false, status: 0 };
    console.error('Fetch failed', e);
    return { ok: false, status: 500 };
  } finally {
    inflight = null;
  }
}

function renderProgram(program: string): void {
  if (!content) return;
  content.innerHTML = '';
  content.style.whiteSpace = 'normal';
  try {
    const blocks = program.split(/\n{2,}/).filter(Boolean);
    if (blocks.length === 0) throw new Error('empty');
    for (const block of blocks) {
      const lines = block.split(/\n/).filter(Boolean);
      if (lines.length === 0) continue;
      const wrapper = document.createElement('div');
      wrapper.className = 'program-day';
      const title = document.createElement('h3');
      title.textContent = lines[0];
      wrapper.appendChild(title);
      const ul = document.createElement('ul');
      for (const line of lines.slice(1)) {
        const li = document.createElement('li');
        li.textContent = line;
        ul.appendChild(li);
      }
      wrapper.appendChild(ul);
      content.appendChild(wrapper);
    }
  } catch {
    content.style.whiteSpace = 'pre-wrap';
    content.textContent = program || '';
  }
}

function renderProgramControls(): void {
  if (!controls) return;
  controls.innerHTML = '';

  const btn = document.createElement('button');
  btn.textContent = t('history');
  btn.addEventListener('click', () => {
    const url = new URL(window.location.toString());
    url.searchParams.set('page', 'history');
    url.searchParams.delete('program_id');
    url.searchParams.delete('type');
    window.history.pushState({}, '', url);
    void loadHistory();
  });

  controls.appendChild(btn);
}

async function loadProgram(programId?: string | null): Promise<void> {
  let message: string | null = null;

  const q = new URLSearchParams();
  q.set('init_data', initData);
  if (programId) q.set('program_id', programId);

  const url = `${API.program}?${q.toString()}`;
  const res = await getJSON<ProgramResp>(url);

  if ('status' in res) {
    message = statusToMessage(res.status);
  } else {
    const data = res.data;
    await applyLang(data.language);
    if (data.error === 'service_unavailable') {
      message = t('service_unavailable');
    } else {
      if (dateEl) {
        const ts = Number(data.created_at);
        dateEl.textContent = Number.isFinite(ts)
          ? `${t('created')}: ${formatDate(ts, document.documentElement.lang || 'en')}`
          : '';
      }
      if (originEl) {
        if (data.coach_type === 'ai_coach') {
          originEl.textContent = t('ai_label');
          originEl.className = 'ai-label';
        } else {
          originEl.textContent = '';
          originEl.className = '';
        }
      }
      renderProgram(data.program || '');
    }
  }

  if (message) {
    setText(message);
    if (dateEl) dateEl.textContent = '';
    if (originEl) {
      originEl.textContent = '';
      originEl.className = '';
    }
  }

  renderProgramControls();

  const next = new URL(window.location.toString());
  next.searchParams.delete('page');
  if (programId && !message) {
    next.searchParams.set('program_id', programId);
  } else {
    next.searchParams.delete('program_id');
  }
  next.searchParams.delete('type');
  window.history.replaceState({}, '', next);
}

async function loadHistory(): Promise<void> {
  if (dateEl) dateEl.textContent = '';
  if (originEl) {
    originEl.textContent = '';
    originEl.className = '';
  }

  const q = new URLSearchParams();
  q.set('init_data', initData);
  const url = `${API.programs}?${q.toString()}`;
  const res = await getJSON<HistoryResp>(url);

  if ('status' in res) {
    setText(statusToMessage(res.status));
    return;
  }

  const data = res.data;
  await applyLang(data.language);
  if (data.error === 'service_unavailable') {
    setText(t('service_unavailable'));
    return;
  }
  if (!data.programs || data.programs.length === 0) {
    setText(t('no_programs'));
    return;
  }
  if (!content) return;

  content.innerHTML = '';
  const list = document.createElement('ul');
  list.className = 'history-list';

  let asc = false;
  let showAI = true;

  function render(): void {
    list.innerHTML = '';
    const items = data.programs!.filter((p) => showAI || p.coach_type !== 'ai_coach');
    items.sort((a, b) => (asc ? a.created_at - b.created_at : b.created_at - a.created_at));

    for (const p of items) {
      const li = document.createElement('li');
      const link = document.createElement('a');
      link.textContent = formatDate(p.created_at, document.documentElement.lang || 'en');
      link.href = '#';
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const url = new URL(window.location.toString());
        url.searchParams.delete('page');
        url.searchParams.set('program_id', String(p.id));
        url.searchParams.delete('type');
        window.history.pushState({}, '', url);
        void loadProgram(String(p.id));
      });
      li.appendChild(link);

      if (p.coach_type === 'ai_coach') {
        const badge = document.createElement('span');
        badge.textContent = ` ${t('ai_label')}`;
        badge.className = 'ai-label';
        li.appendChild(badge);
      }
      list.appendChild(li);
    }
  }

  render();
  content.appendChild(list);

  if (controls) {
    controls.innerHTML = '';
    const orderBtn = document.createElement('button');
    const toggleLabel = document.createElement('label');
    toggleLabel.className = 'toggle';
    const toggleInput = document.createElement('input');
    toggleInput.type = 'checkbox';
    toggleInput.checked = true;
    toggleInput.setAttribute('role', 'switch');
    toggleInput.setAttribute('aria-checked', String(toggleInput.checked));
    toggleInput.addEventListener('change', () => {
      toggleInput.setAttribute('aria-checked', String(toggleInput.checked));
      showAI = toggleInput.checked;
      render();
    });
    const toggleText = document.createElement('span');
    toggleText.textContent = t('show_ai');
    toggleLabel.appendChild(toggleInput);
    toggleLabel.appendChild(toggleText);

    function updateOrderBtn(): void {
      orderBtn.textContent = asc ? t('sort_oldest') : t('sort_newest');
    }

    orderBtn.addEventListener('click', () => {
      asc = !asc;
      updateOrderBtn();
      render();
    });

    updateOrderBtn();
    controls.appendChild(orderBtn);
    controls.appendChild(toggleLabel);
  }
}

async function loadSubscription(): Promise<void> {
  let message: string | null = null;

  if (dateEl) dateEl.textContent = '';
  if (originEl) {
    originEl.textContent = '';
    originEl.className = '';
  }

  const q = new URLSearchParams();
  q.set('init_data', initData);
  const url = `${API.subscription}?${q.toString()}`;
  const res = await getJSON<SubscriptionResp>(url);

  if ('status' in res) {
    message = statusToMessage(res.status);
  } else {
    const data = res.data;
    await applyLang(data.language);
    if (data.error === 'service_unavailable') {
      message = t('service_unavailable');
    } else {
      renderProgram(data.program || '');
    }
  }

  if (message) setText(message);

  renderProgramControls();

  const next = new URL(window.location.toString());
  next.searchParams.set('type', 'subscription');
  window.history.replaceState({}, '', next);
}

function routeFromLocation(): void {
  const params = new URLSearchParams(window.location.search);
  const type = params.get('type');
  const page = params.get('page') ?? 'program';

  if (type === 'subscription') {
    void loadSubscription();
  } else if (page === 'history') {
    void loadHistory();
  } else {
    const programId = params.get('program_id');
    void loadProgram(programId);
  }
}

void (async () => {
  await applyLang('eng');
  if (!initData) {
    setText(t('open_from_telegram'));
    console.error('No Telegram WebApp context: Telegram.WebApp.initData is empty.');
    return;
  }
  try {
    tg?.ready?.();
  } catch {}
  routeFromLocation();
  window.addEventListener('popstate', routeFromLocation);
})();

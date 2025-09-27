import { getProgram, HttpError } from '../api/http';
import type { Locale } from '../api/types';
import { applyLang, t } from '../i18n/i18n';
import { renderLegacyProgram, renderProgramDays, fmtDate } from '../ui/render_program';
import { readInitData } from '../telegram';
import { tmeReady } from '../telegram';

type Ctx = {
  root: HTMLElement;
  content: HTMLElement;
  dateEl: HTMLElement;
  titleEl?: HTMLElement | null;
  button?: HTMLButtonElement | null;
};

type Cleanup = () => void;

function setBusy(node: HTMLElement, busy: boolean) {
  if (busy) node.setAttribute('aria-busy', 'true');
  else node.removeAttribute('aria-busy');
}

function getProgramIdFromURL(): string | null {
  const u = new URL(location.href);
  return u.searchParams.get('id');
}

function normalizeDateNode(rawEl: HTMLElement, root: HTMLElement): HTMLElement {
  let dateEl: HTMLElement = rawEl;

  if (dateEl instanceof HTMLButtonElement) {
    const span = document.createElement('span');
    span.id = dateEl.id;
    span.className = dateEl.className;
    while (dateEl.firstChild) span.appendChild(dateEl.firstChild);
    dateEl.replaceWith(span);
    dateEl = span;
  }

  dateEl.classList.remove('chip', 'badge', 'pill', 'tag');

  const wrapper = dateEl.closest<HTMLElement>('.chip, .badge, .pill, .tag, button');
  if (wrapper && wrapper !== dateEl && root.contains(wrapper)) {
    wrapper.classList.remove('chip', 'badge', 'pill', 'tag');
    wrapper.style.border = 'none';
    wrapper.style.borderRadius = '0';
    wrapper.style.boxShadow = 'none';
    wrapper.style.background = 'transparent';
    wrapper.style.padding = '0';
    if (wrapper.contains(dateEl)) {
      wrapper.replaceWith(dateEl);
    }
  }

  dateEl.setAttribute('role', 'text');
  dateEl.style.border = 'none';
  dateEl.style.borderRadius = '0';
  dateEl.style.boxShadow = 'none';
  dateEl.style.background = 'transparent';
  dateEl.style.padding = '0';

  return dateEl;
}

export async function mountProgramView(
  ctx: Ctx,
  source: 'direct' | 'subscription'
): Promise<Cleanup> {
  const { root, content, titleEl } = ctx;
  let { dateEl } = ctx;
  const initData: string = readInitData();

  const controller = new AbortController();
  if (titleEl) {
    titleEl.textContent = t('page.program');
  }
  setBusy(content, true);

  dateEl = normalizeDateNode(dateEl, root);

  dateEl.hidden = false;
  dateEl.textContent = '';

  try {
    const programId = getProgramIdFromURL();
    const load = await getProgram(programId ?? '', { initData, source, signal: controller.signal });

    const appliedLocale: Locale = await applyLang(load.locale);
    if (titleEl) {
      titleEl.textContent = t('page.program');
    }
    const locale: Locale = appliedLocale;

    content.innerHTML = '';

    if (load.kind === 'structured') {
      if (load.program.created_at) {
        dateEl.textContent = t('program.created', {
          date: fmtDate(load.program.created_at, locale),
        });
      }
      const rendered = renderProgramDays(load.program);
      content.appendChild(rendered.fragment);
    } else {
      if (load.createdAt) {
        dateEl.textContent = t('program.created', {
          date: fmtDate(load.createdAt, locale),
        });
      }
      const rendered = renderLegacyProgram(load.programText, locale);
      content.appendChild(rendered.fragment);
    }

    tmeReady();
  } catch (e) {
    let key = 'unexpected_error';
    if (e instanceof HttpError) key = e.message;
    content.innerHTML = `<div class="notice">${t(key as any)}</div>`;
  } finally {
    setBusy(content, false);
  }

  return () => {
    controller.abort();
  };
}

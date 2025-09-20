import { getProgram, HttpError } from '../api/http';
import type { Locale } from '../api/types';
import { applyLang, t } from '../i18n/i18n';
import { renderLegacyProgram, renderProgramDays, fmtDate } from '../ui/render_program';
import { readInitData } from '../telegram';

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

export async function mountProgramView(
  ctx: Ctx,
  source: 'direct' | 'subscription'
): Promise<Cleanup> {
  const { content, dateEl } = ctx;
  const initData: string = readInitData();

  const controller = new AbortController();
  setBusy(content, true);
  dateEl.hidden = false;
  dateEl.textContent = '';

  try {
    const programId = getProgramIdFromURL();

    // ВАЖНО: вызываем по старой сигнатуре — 2 аргумента (id, opts)
    const load = await getProgram(programId ?? '', {
      initData,
      source,
      signal: controller.signal
    });

    const appliedLocale: Locale = await applyLang(load.locale);
    const locale: Locale = appliedLocale;

    // Рендер
    content.innerHTML = '';
    if (load.kind === 'structured') {
      if (load.program.created_at) {
        dateEl.textContent = t('program.created', {
          date: fmtDate(load.program.created_at, locale)
        });
      }
      const rendered = renderProgramDays(
        { ...load.program, locale },
        locale
      );
      content.appendChild(rendered.fragment);
    } else {
      if (load.createdAt) {
        dateEl.textContent = t('program.created', {
          date: fmtDate(load.createdAt, locale)
        });
      }
      const rendered = renderLegacyProgram(load.programText, locale);
      content.appendChild(rendered.fragment);
    }
  } catch (e) {
    let key = 'unexpected_error';
    if (e instanceof HttpError) key = e.message;
    content.innerHTML = `<div>${t(key as any)}</div>`;
  } finally {
    setBusy(content, false);
  }

  return () => controller.abort();
}

import { LANG_CHANGED_EVENT, t } from '../i18n/i18n';

export type SegmentId = 'program' | 'subscriptions';
export type SegmentChangeHandler = (next: SegmentId) => void;

const SEGMENTS: SegmentId[] = ['program', 'subscriptions'];

type CleanupFn = () => void;

export function renderSegmented(
  container: HTMLElement,
  active: SegmentId,
  onChange: SegmentChangeHandler
): CleanupFn {
  container.innerHTML = '';

  const wrapper = document.createElement('div');
  wrapper.className = 'segmented';
  wrapper.setAttribute('role', 'tablist');

  const buttons: HTMLButtonElement[] = [];
  let currentActive: SegmentId = active;

  const refreshLabels = (): void => {
    wrapper.setAttribute('aria-label', t('tabs.switch_label'));
    buttons.forEach((button) => {
      const id = (button.dataset.tab as SegmentId) ?? 'program';
      const key = id === 'program' ? 'tabs.program' : 'tabs.subscriptions';
      button.textContent = t(key);
    });
  };

  const updateActiveState = (next: SegmentId): void => {
    currentActive = next;
    buttons.forEach((button) => {
      const isActive = button.dataset.tab === next;
      button.setAttribute('aria-selected', String(isActive));
      button.tabIndex = isActive ? 0 : -1;
      button.classList.toggle('is-active', isActive);
    });
  };

  SEGMENTS.forEach((id, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'segmented__tab';
    button.setAttribute('role', 'tab');
    button.dataset.tab = id;
    button.setAttribute('aria-selected', 'false');
    button.tabIndex = -1;

    const labelKey = id === 'program' ? 'tabs.program' : 'tabs.subscriptions';
    button.textContent = t(labelKey);

    button.addEventListener('click', () => {
      if (id !== currentActive) {
        updateActiveState(id);
        onChange(id);
      }
    });

    button.addEventListener('keydown', (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault();
        const direction = event.key === 'ArrowRight' ? 1 : -1;
        const nextIndex = (index + direction + SEGMENTS.length) % SEGMENTS.length;
        buttons[nextIndex].focus();
        return;
      }

      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        if (id !== currentActive) {
          updateActiveState(id);
          onChange(id);
        }
      }
    });

    buttons.push(button);
    wrapper.appendChild(button);
  });

  refreshLabels();
  if (typeof queueMicrotask === 'function') {
    queueMicrotask(refreshLabels);
  } else {
    void Promise.resolve().then(refreshLabels);
  }

  const langListener = (): void => {
    refreshLabels();
  };
  window.addEventListener(LANG_CHANGED_EVENT, langListener);

  updateActiveState(currentActive);
  container.appendChild(wrapper);
  return () => {
    window.removeEventListener(LANG_CHANGED_EVENT, langListener);
  };
}

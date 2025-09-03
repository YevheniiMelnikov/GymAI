import { t } from '../i18n/i18n';

export function createButton(label: string, onClick: () => void): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.addEventListener('click', onClick);
  return btn;
}

export function createToggle(initial: boolean, onChange: (state: boolean) => void): HTMLLabelElement {
  const toggleLabel = document.createElement('label');
  toggleLabel.className = 'toggle';
  const toggleInput = document.createElement('input');
  toggleInput.type = 'checkbox';
  toggleInput.checked = initial;
  toggleInput.setAttribute('role', 'switch');
  toggleInput.setAttribute('aria-checked', String(initial));
  toggleInput.addEventListener('change', () => {
    toggleInput.setAttribute('aria-checked', String(toggleInput.checked));
    onChange(toggleInput.checked);
  });
  const toggleText = document.createElement('span');
  toggleText.textContent = t('show_ai');
  toggleLabel.appendChild(toggleInput);
  toggleLabel.appendChild(toggleText);
  return toggleLabel;
}

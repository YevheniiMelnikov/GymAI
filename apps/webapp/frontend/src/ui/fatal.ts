let rendered = false;

function describe(reason: unknown): string {
  if (reason instanceof Error) return reason.message;
  if (typeof reason === 'string') return reason;
  return '';
}

export function renderFatal(root: HTMLElement, message: string, reason?: unknown): void {
  if (rendered) return;
  rendered = true;

  root.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'fatal-error';
  wrap.setAttribute('role', 'alert');

  const title = document.createElement('h2');
  title.textContent = 'Something went wrong';
  wrap.appendChild(title);

  const msg = document.createElement('p');
  msg.textContent = message;
  wrap.appendChild(msg);

  const hint = document.createElement('p');
  hint.textContent = 'Close and reopen the Mini App to try again.';
  wrap.appendChild(hint);

  const details = describe(reason);
  if (details) {
    const code = document.createElement('pre');
    code.textContent = details;
    code.className = 'fatal-error__details';
    wrap.appendChild(code);
  }

  root.appendChild(wrap);
}

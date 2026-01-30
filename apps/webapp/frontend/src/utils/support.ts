import { getSupportContact } from '../api/http';
import { closeWebApp, openTelegramLink } from '../telegram';

type SupportChatOptions = {
  initData: string;
  supportUrl?: string;
  closeOnOpen?: boolean;
};

export async function openSupportChat(opts: SupportChatOptions): Promise<void> {
  const { initData, supportUrl, closeOnOpen } = opts;
  let url = supportUrl || '';
  if (!url) {
    try {
      const data = await getSupportContact(initData);
      url = data.url || '';
    } catch {
      url = '';
    }
  }
  if (!url) {
    return;
  }
  openTelegramLink(url);
  if (closeOnOpen) {
    closeWebApp();
  }
}

import { applyLang } from './i18n/i18n';
import { initRouter } from './router';

async function bootstrap() {
  try {
    await applyLang();
  } catch {
  }

  initRouter();
}

bootstrap();

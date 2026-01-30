import React, { useCallback, useEffect } from 'react';
import { useI18n } from '../i18n/i18n';
import { openSupportChat } from '../utils/support';
import type { GenerationFailurePayload } from '../ui/generation_failure';

type GenerationFailedModalProps = {
  payload: GenerationFailurePayload;
  initData: string;
  onClose: () => void;
};

const GenerationFailedModal: React.FC<GenerationFailedModalProps> = ({ payload, initData, onClose }) => {
  const { t } = useI18n();
  const { creditsRefunded, supportChatEnabled, errorCode, correlationId } = payload;

  useEffect(() => {
    if (errorCode || correlationId) {
      console.info('generation_failed_modal_shown', {
        feature: payload.feature,
        error_code: errorCode,
        correlation_id: correlationId,
        credits_refunded: creditsRefunded
      });
    }
  }, [payload.feature, errorCode, correlationId, creditsRefunded]);

  const handleSupport = useCallback(() => {
    if (!supportChatEnabled) {
      return;
    }
    void openSupportChat({ initData, closeOnOpen: true });
  }, [initData, supportChatEnabled]);

  const bodyKey: 'modal.generationFailed.bodyCreditsRefunded' | 'modal.generationFailed.body' = creditsRefunded
    ? 'modal.generationFailed.bodyCreditsRefunded'
    : 'modal.generationFailed.body';

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="subscription-confirm"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="subscription-confirm__dialog">
        <h3 className="subscription-confirm__title">{t('modal.generationFailed.title')}</h3>
        <p className="subscription-confirm__body">{t(bodyKey)}</p>
        <div className="subscription-confirm__actions">
          <button
            type="button"
            className="subscription-confirm__btn subscription-confirm__btn--confirm"
            onClick={handleSupport}
            disabled={!supportChatEnabled}
          >
            {t('modal.generationFailed.supportButton')}
          </button>
          <button
            type="button"
            className="subscription-confirm__btn subscription-confirm__btn--cancel"
            onClick={onClose}
          >
            {t('modal.generationFailed.closeButton')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default GenerationFailedModal;

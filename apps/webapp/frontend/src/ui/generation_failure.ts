export type GenerationFeature = 'workouts' | 'diets';

export type GenerationFailurePayload = {
  feature: GenerationFeature;
  errorCode: string | null;
  messageKey: string | null;
  creditsRefunded: boolean;
  correlationId: string | null;
  supportChatEnabled: boolean;
};

export const GENERATION_FAILED_EVENT = 'generation-failed';

export function emitGenerationFailed(payload: GenerationFailurePayload): void {
  try {
    window.dispatchEvent(new CustomEvent(GENERATION_FAILED_EVENT, { detail: payload }));
  } catch {}
}

export function parseGenerationFailure(
  feature: GenerationFeature,
  data: any
): GenerationFailurePayload {
  const errorCode =
    typeof data?.error_code === 'string'
      ? data.error_code
      : typeof data?.error === 'string'
      ? data.error
      : typeof data?.reason === 'string'
      ? data.reason
      : null;
  const messageKey =
    typeof data?.localized_message_key === 'string'
      ? data.localized_message_key
      : typeof data?.message_key === 'string'
      ? data.message_key
      : null;
  const correlationId =
    typeof data?.correlation_id === 'string'
      ? data.correlation_id
      : typeof data?.request_id === 'string'
      ? data.request_id
      : null;
  const creditsRefunded = Boolean(data?.credits_refunded);
  const supportChatEnabled =
    typeof data?.support_contact_action === 'boolean'
      ? data.support_contact_action
      : typeof data?.support_chat_enabled === 'boolean'
      ? data.support_chat_enabled
      : true;
  return {
    feature,
    errorCode,
    messageKey,
    creditsRefunded,
    correlationId,
    supportChatEnabled,
  };
}

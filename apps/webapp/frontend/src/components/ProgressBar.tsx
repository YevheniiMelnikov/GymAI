import React from 'react';
import { useI18n } from '../i18n/i18n';
import './ProgressBar.css';

const STATIC_PREFIX = ((window as any).__STATIC_PREFIX__ as string | undefined) ?? '/static/';
const STATIC_VERSION = ((window as any).__STATIC_VERSION__ as string | undefined) ?? '';

interface ProgressBarProps {
    progress: number;
    stage?: string;
    onClose: () => void;
}

const ProgressBar: React.FC<ProgressBarProps> = ({ onClose }) => {
    const { t } = useI18n();
    void onClose;
    return (
        <div className="progress-view" aria-live="polite" aria-busy="true">
            <div className="progress-view__content">
                <img
                    className="progress-view__art"
                    src={`${STATIC_PREFIX}images/processing.png${STATIC_VERSION ? `?v=${STATIC_VERSION}` : ''}`}
                    alt={t('progress.processing', { defaultValue: 'Cooking your plan...' })}
                    loading="eager"
                />
                <span className="progress-view__spinner" aria-hidden="true" />
                <p className="progress-view__hint">{t('progress.hint')}</p>
            </div>
        </div>
    );
};

export default ProgressBar;

import React from 'react';
import { useI18n } from '../i18n/i18n';
import './ProgressBar.css';

interface ProgressBarProps {
    progress: number;
    stage?: string;
    onClose: () => void;
}

const ProgressBar: React.FC<ProgressBarProps> = ({ onClose }) => {
    const { t } = useI18n();
    return (
        <div style={{
            width: '90%',
            maxWidth: '400px',
            background: 'var(--tg-theme-bg-color, #ffffff)',
            padding: '24px',
            borderRadius: '16px',
            boxShadow: '0 4px 24px rgba(0, 0, 0, 0.15)',
            textAlign: 'center',
            color: 'var(--tg-theme-text-color, #000000)',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
            margin: '20px auto',
        }}>
            <div className="progress-view__spinner-container" style={{ display: 'flex', justifyContent: 'center', marginBottom: '10px' }}>
                <div style={{
                    width: '40px',
                    height: '40px',
                    border: '3px solid var(--tg-theme-secondary-bg-color, #e0e0e0)',
                    borderTop: '3px solid var(--tg-theme-button-color, #007AFF)',
                    borderRadius: '50%',
                    animation: 'spin 1s linear infinite'
                }}>
                    <style>{`@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }`}</style>
                </div>
            </div>
            <div className="progress-view__info-container">
                <div className="progress-view__stage" style={{ fontSize: '16px', color: 'var(--tg-theme-text-color, #000000)', marginTop: '4px', fontWeight: 500 }}>
                    {t('progress.processing', { defaultValue: 'Cooking your plan...' })}
                </div>
            </div>
            <p className="progress-view__hint" style={{ fontSize: '13px', color: 'var(--tg-theme-hint-color, #8e8e93)', lineHeight: 1.4, margin: 0 }}>
                {t('progress.hint')}
            </p>
            <div className="progress-view__actions" style={{ marginTop: '8px' }}>
                <button
                    className="primary-button progress-view__close"
                    onClick={onClose}
                    style={{
                        width: '100%',
                        padding: '12px',
                        borderRadius: '12px',
                        backgroundColor: 'var(--tg-theme-secondary-bg-color, #efeff4)',
                        color: 'var(--tg-theme-text-color, #000000)',
                        fontWeight: 600,
                        border: 'none',
                        cursor: 'pointer'
                    }}
                >
                    {t('progress.close_app')}
                </button>
            </div>
        </div>
    );
};

export default ProgressBar;

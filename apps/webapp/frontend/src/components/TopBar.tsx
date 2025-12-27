import React from 'react';
import { t } from '../i18n/i18n';

type TopBarProps = {
    title: string;
    onBack?: () => void;
};

const TopBar: React.FC<React.PropsWithChildren<TopBarProps>> = ({ title, onBack, children }) => {
    const leadingStyle: React.CSSProperties = { marginLeft: '-6px' };
    const backStyle: React.CSSProperties = { padding: '6px' };

    const renderBackControl = () => {
        if (!onBack) {
            return <span aria-hidden="true" className="topbar__spacer" />;
        }
        return (
            <button
                type="button"
                className="topbar__back"
                aria-label={t('back')}
                onClick={onBack}
                style={backStyle}
            >
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <line
                        x1="15"
                        y1="6"
                        x2="9"
                        y2="12"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                    />
                    <line
                        x1="15"
                        y1="18"
                        x2="9"
                        y2="12"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                    />
                </svg>
            </button>
        );
    };

    return (
        <header className="topbar" role="banner">
            <div className="topbar__leading" style={leadingStyle}>
                {renderBackControl()}
            </div>

            <h1 id="page-title" className="topbar__title">
                {title}
            </h1>

            <div className="topbar__actions" aria-hidden={!children}>
                {children ?? <span aria-hidden="true" className="topbar__spacer" />}
            </div>
        </header>
    );
};

export default TopBar;

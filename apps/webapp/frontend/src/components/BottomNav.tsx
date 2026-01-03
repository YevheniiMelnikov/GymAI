import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { t } from '../i18n/i18n';

type NavItem = {
    key: 'faq' | 'archive' | 'workouts' | 'profile';
    label: string;
    path: string;
    icon: string;
    isActive: (pathName: string) => boolean;
};

const STATIC_PREFIX = ((window as any).__STATIC_PREFIX__ as string | undefined) ?? '/static/';

const NAV_ITEMS: Array<Omit<NavItem, 'label'>> = [
    {
        key: 'faq',
        path: '/faq',
        icon: `${STATIC_PREFIX}images/faq.svg`,
        isActive: (pathName) => pathName.startsWith('/faq'),
    },
    {
        key: 'archive',
        path: '/history',
        icon: `${STATIC_PREFIX}images/archive.svg`,
        isActive: (pathName) => pathName.startsWith('/history'),
    },
    {
        key: 'workouts',
        path: '/',
        icon: `${STATIC_PREFIX}images/workouts.svg`,
        isActive: (pathName) => pathName === '/',
    },
    {
        key: 'profile',
        path: '/profile',
        icon: `${STATIC_PREFIX}images/profile.svg`,
        isActive: (pathName) => pathName.startsWith('/profile'),
    },
];

type BottomNavProps = {
    activeKey?: NavItem['key'];
};

const BottomNav: React.FC<BottomNavProps> = ({ activeKey }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const pathName = location.pathname;

    return (
        <nav className="bottom-nav" aria-label="Primary">
            {NAV_ITEMS.map((item) => {
                const active = activeKey ? item.key === activeKey : item.isActive(pathName);
                const label =
                    item.key === 'faq'
                        ? t('nav.faq')
                        : item.key === 'archive'
                        ? t('nav.archive')
                        : item.key === 'profile'
                        ? t('nav.profile')
                        : t('nav.workouts');
                return (
                    <button
                        key={item.key}
                        type="button"
                        className={`bottom-nav__item ${active ? 'is-active' : ''}`}
                        onClick={() => {
                            if (active) {
                                return;
                            }
                            const tg = (window as any).Telegram?.WebApp;
                            try {
                                tg?.HapticFeedback?.impactOccurred('light');
                            } catch {
                            }
                            navigate(item.path);
                        }}
                        aria-current={active ? 'page' : undefined}
                    >
                        <span
                            className="bottom-nav__icon"
                            style={{ '--icon-url': `url(${item.icon})` } as React.CSSProperties}
                            aria-hidden="true"
                        />
                        <span className="bottom-nav__label">{label}</span>
                    </button>
                );
            })}
        </nav>
    );
};

export default BottomNav;

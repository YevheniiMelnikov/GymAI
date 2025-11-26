import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { renderSegmented, SegmentId } from '../components/Segmented';
import TopBar from '../components/TopBar';
import { applyLang, t } from '../i18n/i18n';
import { readInitData, readLocale, showBackButton, hideBackButton, onBackButtonClick, offBackButtonClick } from '../telegram';
import type { HistoryItem, HistoryResp, Locale } from '../api/types';

async function getHistory(locale: Locale): Promise<HistoryResp> {
    const headers: Record<string, string> = {};
    const initData = readInitData();
    if (initData) headers['X-Telegram-InitData'] = initData;
    // We need to construct the URL correctly.
    // Since we are in a SPA, window.location.href might be different.
    // But the API endpoint is relative to the root usually.
    // The original code used new URL('api/programs/', window.location.href).
    // We can just use '/api/programs/'.
    const url = new URL('/api/programs/', window.location.origin);
    url.searchParams.set('locale', locale);
    const resp = await fetch(url.toString(), { headers });
    if (!resp.ok) throw new Error('unexpected_error');
    return (await resp.json()) as HistoryResp;
}

const HistoryPage: React.FC = () => {
    const navigate = useNavigate();
    const switcherRef = useRef<HTMLDivElement>(null);
    const fallbackIllustration =
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='360' height='260' viewBox='0 0 360 260' fill='none'><defs><linearGradient id='g1' x1='50' y1='30' x2='310' y2='210' gradientUnits='userSpaceOnUse'><stop stop-color='%23C7DFFF'/><stop offset='1' stop-color='%23E7EEFF'/></linearGradient><linearGradient id='g2' x1='120' y1='80' x2='240' y2='200' gradientUnits='userSpaceOnUse'><stop stop-color='%237AA7FF'/><stop offset='1' stop-color='%235B8BFF'/></linearGradient></defs><rect x='30' y='24' width='300' height='200' rx='28' fill='url(%23g1)'/><rect x='62' y='56' width='236' height='136' rx='18' fill='white' stroke='%23B8C7E6' stroke-width='3'/><path d='M90 174c18-30 42-30 60 0s42 30 60 0 42-30 60 0' stroke='%23A7B9DB' stroke-width='6' stroke-linecap='round' fill='none'/><circle cx='136' cy='106' r='16' fill='url(%23g2)'/><circle cx='216' cy='118' r='12' fill='%23E6ECFC'/><circle cx='248' cy='94' r='8' fill='%23E6ECFC'/></svg>";
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [data, setData] = useState<HistoryResp | null>(null);
    const [locale, setLocale] = useState<string>('en');
    const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const [activeSegment, setActiveSegment] = useState<SegmentId>('program');
    const dropdownRef = useRef<HTMLDivElement>(null);
    const activeItems = useMemo<HistoryItem[]>(
        () => (activeSegment === 'subscriptions' ? data?.subscriptions : data?.programs) ?? [],
        [activeSegment, data]
    );
    const canSort = activeItems.length > 1;

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsDropdownOpen(false);
            }
        };
        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setIsDropdownOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('keydown', handleEscape);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('keydown', handleEscape);
        };
    }, []);

    useEffect(() => {
        if (!canSort) {
            setIsDropdownOpen(false);
        }
    }, [canSort]);

    useEffect(() => {
        if (switcherRef.current) {
            return renderSegmented(switcherRef.current, activeSegment, (next) => {
                setActiveSegment(next);
            });
        }
    }, []);

    const handleBack = useCallback(() => {
        if (window.history.length > 1) {
            navigate(-1);
            return;
        }
        navigate('/');
    }, [navigate]);

    useEffect(() => {
        showBackButton();
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [handleBack]);

    useEffect(() => {
        const fetchData = async () => {
            setLoading(true);
            setError(null);
            try {
                const requestLocale = readLocale();
                const historyData = await getHistory(requestLocale);
                const appliedLang = await applyLang(historyData.language ?? requestLocale);
                setLocale(appliedLang);
                setData(historyData);
            } catch {
                setError(t('unexpected_error'));
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    const sortedItems = useMemo(() => {
        if (activeItems.length === 0) return [];
        return [...activeItems].sort((a, b) => {
            if (sortOrder === 'newest') {
                return b.created_at - a.created_at;
            }
            return a.created_at - b.created_at;
        });
    }, [activeItems, sortOrder]);

    const handleProgramClick = (id: number) => {
        navigate(`/?id=${id}`);
    };

    return (
        <div className="page-container">
            <TopBar title={t('page.history')} onBack={handleBack} />

            <div className="page-shell">
                <div id="content" aria-busy={loading}>
                    <div className="history-panel">
                        <div ref={switcherRef} id="segmented" className="segmented-container" />

                        {canSort && (
                            <div className="history-controls" ref={dropdownRef}>
                                <div className="sort-menu">
                                    <button
                                        type="button"
                                        className="sort-trigger"
                                        aria-haspopup="listbox"
                                        aria-expanded={isDropdownOpen}
                                        onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                                    >
                                        <span className="sort-trigger__icon" aria-hidden="true">
                                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                                                <path
                                                    d="M12 3L8.5 6.5H11V13h2V6.5h2.5L12 3Z"
                                                    stroke="currentColor"
                                                    strokeWidth="1.6"
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    fill="none"
                                                />
                                                <path
                                                    d="M12 21l3.5-3.5H13V11h-2v6.5H8.5L12 21Z"
                                                    stroke="currentColor"
                                                    strokeWidth="1.6"
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    fill="none"
                                                />
                                            </svg>
                                        </span>
                                        <span>{sortOrder === 'newest' ? t('sort_newest') : t('sort_oldest')}</span>
                                        <span className="sort-trigger__chevron" aria-hidden="true">
                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                                                <path
                                                    d="M7 10l5 5 5-5"
                                                    stroke="currentColor"
                                                    strokeWidth="2"
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                />
                                            </svg>
                                        </span>
                                    </button>

                                    {isDropdownOpen && (
                                        <div className="sort-dropdown" role="listbox">
                                            <button
                                                type="button"
                                                className={`sort-option ${sortOrder === 'newest' ? 'is-active' : ''}`}
                                                onClick={() => {
                                                    setSortOrder('newest');
                                                    setIsDropdownOpen(false);
                                                }}
                                            >
                                                {t('sort_newest')}
                                            </button>
                                            <button
                                                type="button"
                                                className={`sort-option ${sortOrder === 'oldest' ? 'is-active' : ''}`}
                                                onClick={() => {
                                                    setSortOrder('oldest');
                                                    setIsDropdownOpen(false);
                                                }}
                                            >
                                                {t('sort_oldest')}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {error && <div className="error-block">{error}</div>}

                        {!loading && !error && sortedItems.length > 0 && (
                            <ul className="week centered">
                                {sortedItems.map((it) => {
                                    const formattedDate = new Date(it.created_at * 1000).toLocaleDateString(locale, {
                                        day: 'numeric',
                                        month: 'long',
                                        year: 'numeric',
                                    });
                                    return (
                                        <li key={it.id} className="program-day">
                                            {activeSegment === 'program' ? (
                                                <a
                                                    href="#"
                                                    onClick={(e) => {
                                                        e.preventDefault();
                                                        handleProgramClick(it.id);
                                                    }}
                                                    className="program-day-summary"
                                                >
                                                    {formattedDate}
                                                </a>
                                            ) : (
                                                <div className="program-day-summary">
                                                    {formattedDate}
                                                </div>
                                            )}
                                        </li>
                                    );
                                })}
                            </ul>
                        )}

                        {!loading && !error && sortedItems.length === 0 && (
                            <div className="empty-state history-empty" style={{ textAlign: 'center' }}>
                                <img
                                    src="/static/images/404.png"
                                    alt={activeSegment === 'subscriptions' ? t('subscriptions.title') : t('no_programs')}
                                    style={{
                                        width: 'clamp(160px, 46vw, 200px)',
                                        height: 'clamp(120px, 36vw, 170px)',
                                        objectFit: 'contain',
                                        margin: '0 auto',
                                        display: 'block',
                                    }}
                                    onError={(ev) => {
                                        const target = ev.currentTarget;
                                        if (target.src !== fallbackIllustration) {
                                            target.src = fallbackIllustration;
                                        }
                                    }}
                                />
                                <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text)', margin: 0 }}>
                                    {activeSegment === 'subscriptions' ? t('subscriptions.empty') : t('no_programs')}
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default HistoryPage;

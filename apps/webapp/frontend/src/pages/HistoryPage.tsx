import React, { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { applyLang, t } from '../i18n/i18n';
import { readInitData, readLocale, showBackButton, hideBackButton, onBackButtonClick, offBackButtonClick } from '../telegram';
import type { HistoryResp, Locale } from '../api/types';

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
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [data, setData] = useState<HistoryResp | null>(null);
    const [locale, setLocale] = useState<string>('en');
    const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');

    useEffect(() => {
        showBackButton();
        const handleBack = () => navigate('/');
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [navigate]);

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

    const sortedPrograms = useMemo(() => {
        if (!data?.programs) return [];
        return [...data.programs].sort((a, b) => {
            if (sortOrder === 'newest') {
                return b.created_at - a.created_at;
            } else {
                return a.created_at - b.created_at;
            }
        });
    }, [data, sortOrder]);

    const handleProgramClick = (id: number) => {
        navigate(`/?id=${id}`);
    };

    return (
        <div className="page-container">
            <h1 id="page-title">{t('page.history')}</h1>

            <div id="content" aria-busy={loading}>
                <div className="week">
                    <div className="sort-container" style={{ display: 'flex', justifyContent: 'center', marginBottom: '16px' }}>
                        <select
                            className="sort-select"
                            value={sortOrder}
                            onChange={(e) => setSortOrder(e.target.value as 'newest' | 'oldest')}
                            style={{
                                appearance: 'none',
                                backgroundColor: 'var(--surface)',
                                color: 'var(--text)',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                padding: '8px 16px',
                                fontSize: '14px',
                                fontWeight: 600,
                                cursor: 'pointer',
                                textAlign: 'center',
                                outline: 'none',
                            }}
                        >
                            <option value="newest">{t('sort_newest')}</option>
                            <option value="oldest">{t('sort_oldest')}</option>
                        </select>
                    </div>

                    {error && <div className="error-block">{error}</div>}

                    {!loading && !error && (
                        <ul className="week">
                            {sortedPrograms.length > 0 ? (
                                sortedPrograms.map((it) => (
                                    <li key={it.id} className="program-day">
                                        <a
                                            href="#"
                                            onClick={(e) => {
                                                e.preventDefault();
                                                handleProgramClick(it.id);
                                            }}
                                            className="program-day-summary"
                                        >
                                            {new Date(it.created_at * 1000).toLocaleDateString(locale, {
                                                day: 'numeric',
                                                month: 'long',
                                                year: 'numeric',
                                            })}
                                        </a>
                                    </li>
                                ))
                            ) : (
                                !loading && (
                                    <div className="empty-state" style={{ textAlign: 'center', marginTop: '40px' }}>
                                        <img
                                            src="/static/images/404.png"
                                            alt="No programs"
                                            style={{ maxWidth: '200px', marginBottom: '16px' }}
                                        />
                                        <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text)' }}>
                                            {t('no_programs')}
                                        </p>
                                    </div>
                                )
                            )}
                        </ul>
                    )}
                </div>
            </div>
        </div>
    );
};

export default HistoryPage;

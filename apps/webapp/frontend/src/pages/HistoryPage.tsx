import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { applyLang, t } from '../i18n/i18n';
import { readInitData, readLocale } from '../telegram';
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

    const handleProgramClick = (id: number) => {
        // Navigate to program page with id
        navigate(`/?id=${id}`);
    };

    return (
        <div className="page-container">
            <h1 id="page-title">{t('page.history')}</h1>

            <div id="content" aria-busy={loading}>
                <div className="week">
                    <h2>{t('history')}</h2>

                    {error && <div className="error-block">{error}</div>}

                    {!loading && !error && (
                        <ul className="history-list">
                            {data?.programs && data.programs.length > 0 ? (
                                data.programs.map((it) => (
                                    <li key={it.id}>
                                        <a
                                            href="#"
                                            onClick={(e) => {
                                                e.preventDefault();
                                                handleProgramClick(it.id);
                                            }}
                                        >
                                            {new Date(it.created_at * 1000).toLocaleString(locale)}
                                        </a>
                                    </li>
                                ))
                            ) : (
                                !loading && <p className="history-empty">{t('no_programs')}</p>
                            )}
                        </ul>
                    )}
                </div>
            </div>
        </div>
    );
};

export default HistoryPage;

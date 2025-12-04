import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getProgram, getSubscription, HttpError } from '../api/http';
import { applyLang, t } from '../i18n/i18n';
import { renderProgramDays, renderLegacyProgram, fmtDate } from '../ui/render_program';
import { readInitData, tmeReady } from '../telegram';
import type { Locale, Program } from '../api/types';
import { renderSegmented, SegmentId } from '../components/Segmented';
import TopBar from '../components/TopBar';

const ProgramPage: React.FC = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const searchParamsKey = searchParams.toString();
    const navigate = useNavigate();
    const contentRef = useRef<HTMLDivElement>(null);
    const switcherRef = useRef<HTMLDivElement>(null);
    const fallbackIllustration =
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='360' height='260' viewBox='0 0 360 260' fill='none'><defs><linearGradient id='g1' x1='50' y1='30' x2='310' y2='210' gradientUnits='userSpaceOnUse'><stop stop-color='%23C7DFFF'/><stop offset='1' stop-color='%23E7EEFF'/></linearGradient><linearGradient id='g2' x1='120' y1='80' x2='240' y2='200' gradientUnits='userSpaceOnUse'><stop stop-color='%237AA7FF'/><stop offset='1' stop-color='%235B8BFF'/></linearGradient></defs><rect x='30' y='24' width='300' height='200' rx='28' fill='url(%23g1)'/><rect x='62' y='56' width='236' height='136' rx='18' fill='white' stroke='%23B8C7E6' stroke-width='3'/><path d='M90 174c18-30 42-30 60 0s42 30 60 0 42-30 60 0' stroke='%23A7B9DB' stroke-width='6' stroke-linecap='round' fill='none'/><circle cx='136' cy='106' r='16' fill='url(%23g2)'/><circle cx='216' cy='118' r='12' fill='%23E6ECFC'/><circle cx='248' cy='94' r='8' fill='%23E6ECFC'/></svg>";
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [dateText, setDateText] = useState('');
    const initialSegment: SegmentId =
        (searchParams.get('source') || '') === 'subscription' ? 'subscriptions' : 'program';
    const [activeSegment, setActiveSegment] = useState<SegmentId>(initialSegment);

    const programId = searchParams.get('id') || '';
    const paramLang = searchParams.get('lang') || undefined;

    useEffect(() => {
        void applyLang(paramLang);
    }, [paramLang]);

    useEffect(() => {
        const params = new URLSearchParams(searchParamsKey);
        const nextSegment: SegmentId = (params.get('source') || '') === 'subscription' ? 'subscriptions' : 'program';
        setActiveSegment((prev) => (prev === nextSegment ? prev : nextSegment));
    }, [searchParamsKey]);

    useEffect(() => {
        if (!switcherRef.current) return;
        return renderSegmented(switcherRef.current, activeSegment, (next) => {
            setActiveSegment(next);
            const nextParams = new URLSearchParams(searchParamsKey);
            if (next === 'subscriptions') {
                nextParams.set('source', 'subscription');
            } else {
                nextParams.delete('source');
            }
            setSearchParams(nextParams, { replace: true });
        });
    }, [activeSegment, searchParamsKey, setSearchParams]);

    useEffect(() => {
        const controller = new AbortController();
        const initData = readInitData();

        const fetchData = async () => {
            setLoading(true);
            setError(null);
            setDateText('');
            if (contentRef.current) contentRef.current.innerHTML = '';

            try {
                let appliedLocale: Locale = 'en';
                let programData: Program | null = null;
                let legacyText: string | null = null;
                let createdAt: string | null = null;

                if (activeSegment === 'program') {
                    const load = await getProgram(programId, { initData, source: 'direct', signal: controller.signal });
                    appliedLocale = await applyLang(load.locale || paramLang);

                    if (load.kind === 'structured') {
                        programData = load.program;
                    } else {
                        legacyText = load.programText;
                        createdAt = load.createdAt ?? null;
                    }
                } else {
                    // Subscriptions
                    const sub = await getSubscription(initData, controller.signal);
                    appliedLocale = await applyLang(sub.language || paramLang);

                    if (sub.days) {
                        programData = {
                            id: sub.id || 'sub',
                            locale: appliedLocale,
                            created_at: null,
                            days: sub.days
                        };
                    } else if (sub.program) {
                        legacyText = sub.program;
                    } else {
                        throw new Error('no_programs');
                    }
                }

                // Render content
                if (contentRef.current) {
                    contentRef.current.innerHTML = '';
                    if (programData) {
                        if (programData.created_at) {
                            setDateText(t('program.created', { date: fmtDate(programData.created_at, appliedLocale) }));
                        }
                        const { fragment } = renderProgramDays(programData);
                        contentRef.current.appendChild(fragment);
                    } else if (legacyText) {
                        if (createdAt) {
                            setDateText(t('program.created', { date: fmtDate(createdAt, appliedLocale) }));
                        }
                        const { fragment } = renderLegacyProgram(legacyText, appliedLocale);
                        contentRef.current.appendChild(fragment);
                    }
                }
                tmeReady();
            } catch (e) {
                let key = 'unexpected_error';
                if (e instanceof HttpError) {
                    if (e.status === 404) {
                        key = activeSegment === 'subscriptions' ? 'subscriptions.empty' : 'no_programs';
                    } else {
                        key = e.message;
                    }
                } else if (e instanceof Error && e.message === 'no_programs') {
                    key = 'subscriptions.empty';
                }
                setError(t(key as any));
            } finally {
                setLoading(false);
            }
        };

        fetchData();

        return () => {
            controller.abort();
        };
    }, [programId, activeSegment, paramLang]);

    return (
        <div className="page-container">
            <TopBar title={t('program.title')} />

            <div className="page-shell">
                <div id="content" aria-busy={loading}>
                    <div className="history-panel program-panel">
                        <div ref={switcherRef} id="segmented" className="segmented-container" />

                        <div ref={contentRef} className="week centered" />
                        <div id="program-date" hidden={!dateText}>
                            {dateText}
                        </div>

                        {loading && <div aria-busy="true">Loading...</div>}
                        {error && (
                            <div className="empty-state history-empty">
                                <img
                                    src="/static/images/404.png"
                                    alt={t('no_programs')}
                                    className="history-empty__image"
                                    onError={(ev) => {
                                        const target = ev.currentTarget;
                                        if (target.src !== fallbackIllustration) {
                                            target.src = fallbackIllustration;
                                        }
                                    }}
                                />
                                <p className="history-empty__caption">{error}</p>
                            </div>
                        )}
                    </div>
                </div>

                <div className="history-footer">
                    <button
                        type="button"
                        id="history-button"
                        className="primary-button"
                        onClick={() => navigate('/history')}
                    >
                        {t('program.view_history')}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ProgramPage;

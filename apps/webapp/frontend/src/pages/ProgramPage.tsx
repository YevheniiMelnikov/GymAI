import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getProgram, getSubscription, HttpError } from '../api/http';
import { applyLang, t } from '../i18n/i18n';
import { renderProgramDays, renderLegacyProgram, fmtDate } from '../ui/render_program';
import { readInitData, tmeReady } from '../telegram';
import type { Locale, Program } from '../api/types';
import { renderSegmented, SegmentId } from '../components/Segmented';

const ProgramPage: React.FC = () => {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const contentRef = useRef<HTMLDivElement>(null);
    const switcherRef = useRef<HTMLDivElement>(null);
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
        if (switcherRef.current) {
            return renderSegmented(switcherRef.current, activeSegment, (next) => {
                setActiveSegment(next);
            });
        }
    }, []);

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
            <h1 id="page-title">{t('program.title')}</h1>

            <div ref={switcherRef} id="segmented" className="segmented-container" />

            <div id="content" ref={contentRef} aria-busy={loading} />
            <div id="program-date" hidden={!dateText}>{dateText}</div>

            {loading && <div aria-busy="true">Loading...</div>}
            {error && <div className="notice">{error}</div>}

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
    );
};

export default ProgramPage;

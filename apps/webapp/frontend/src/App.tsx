import React, { useEffect, useMemo, useRef, useState } from 'react';
import { BrowserRouter, Routes, Route, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import ProgramPage from './pages/ProgramPage';
import HistoryPage from './pages/HistoryPage';
import PaymentPage from './pages/PaymentPage';
import TopupPage from './pages/TopupPage';
import FaqPage from './pages/FaqPage';
import WeeklySurveyPage from './pages/WeeklySurveyPage';
import ProfilePage from './pages/ProfilePage';
import RegistrationRequiredPage from './pages/RegistrationRequiredPage';
import WorkoutFlowPage from './pages/WorkoutFlowPage';
import DietPage from './pages/DietPage';
import DietFlowPage from './pages/DietFlowPage';
import GenerationFailedModal from './components/GenerationFailedModal';
import { useTelegramInit } from './hooks/useTelegramInit';
import { getProfile, HttpError } from './api/http';
import { applyLang, LANG_CHANGED_EVENT } from './i18n/i18n';
import { readInitData } from './telegram';
import {
    GENERATION_FAILED_EVENT,
    emitGenerationFailed,
    parseGenerationFailure,
    type GenerationFailurePayload,
} from './ui/generation_failure';

const LANG_STORAGE_KEY = 'app:lang';
const WORKOUT_TASK_KEY = 'generation_task_id_workout';
const DIET_TASK_KEY = 'generation_task_id_diet';
const WORKOUT_PLAN_TYPE_KEY = 'generation_plan_type_workout';

// Component to handle legacy query params redirection
const LegacyRedirect = () => {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();

    useEffect(() => {
        const params = new URLSearchParams(searchParams);
        const type = params.get('type');
        params.delete('type');
        const search = params.toString();
        const withSearch = (path: string) => (search ? `${path}?${search}` : path);

        if (type === 'history') {
            navigate(withSearch('/history'), { replace: true });
        } else if (type === 'payment') {
            navigate(withSearch('/payment'), { replace: true });
        } else if (type === 'topup') {
            navigate(withSearch('/topup'), { replace: true });
        } else if (type === 'profile') {
            navigate(withSearch('/profile'), { replace: true });
        } else if (type === 'faq') {
            navigate(withSearch('/faq'), { replace: true });
        } else if (type === 'weekly_survey') {
            navigate(withSearch('/weekly-survey'), { replace: true });
        } else if (type === 'diet') {
            navigate(withSearch('/diets'), { replace: true });
        } else if (type === 'program') {
            navigate(withSearch('/'), { replace: true });
        }
    }, [searchParams, navigate]);

    return null;
};

const GlobalGenerationRedirect: React.FC = () => {
    const navigate = useNavigate();
    const location = useLocation();
    const pollRef = useRef<number | null>(null);
    const inFlightRef = useRef<Set<string>>(new Set());

    useEffect(() => {
        const getStoredLang = () => {
            try {
                return window.sessionStorage.getItem(LANG_STORAGE_KEY) ?? '';
            } catch {
                return '';
            }
        };

        const buildQuery = (entries: Array<[string, string | null | undefined]>): string => {
            const params = new URLSearchParams();
            const storedLang = getStoredLang();
            if (storedLang) {
                params.set('lang', storedLang);
            }
            entries.forEach(([key, value]) => {
                if (!value) {
                    return;
                }
                params.set(key, value);
            });
            const query = params.toString();
            return query ? `?${query}` : '';
        };

        const clearKey = (key: string) => {
            try {
                window.localStorage.removeItem(key);
            } catch {
            }
        };

        const failAndClear = (kind: 'workout' | 'diet', data: unknown) => {
            if (kind === 'workout') {
                clearKey(WORKOUT_TASK_KEY);
                clearKey(WORKOUT_PLAN_TYPE_KEY);
            } else {
                clearKey(DIET_TASK_KEY);
            }
            const payload = parseGenerationFailure(kind === 'diet' ? 'diets' : 'workouts', data);
            emitGenerationFailed(payload);
        };

        const pollTask = async (taskId: string, kind: 'workout' | 'diet') => {
            if (inFlightRef.current.has(taskId)) {
                return;
            }
            inFlightRef.current.add(taskId);
            try {
                const resp = await fetch(`/api/generation-status/?task_id=${encodeURIComponent(taskId)}`);
                if (!resp.ok) {
                    failAndClear(kind, null);
                    return;
                }
                let data: any = null;
                try {
                    data = await resp.json();
                } catch {
                    failAndClear(kind, null);
                    return;
                }
                if (data.status === 'success') {
                    const resultId = data.result_id ? String(data.result_id) : '';
                    if (kind === 'workout') {
                        const planType = window.localStorage.getItem(WORKOUT_PLAN_TYPE_KEY);
                        clearKey(WORKOUT_TASK_KEY);
                        clearKey(WORKOUT_PLAN_TYPE_KEY);
                        if (resultId) {
                            const query = planType === 'subscription'
                                ? buildQuery([['subscription_id', resultId], ['source', 'subscription']])
                                : buildQuery([['program_id', resultId]]);
                            navigate(`/${query}`);
                        } else {
                            navigate('/');
                        }
                    } else {
                        clearKey(DIET_TASK_KEY);
                        if (resultId) {
                            const query = buildQuery([['diet_id', resultId]]);
                            navigate(`/diets${query}`);
                        } else {
                            navigate('/diets');
                        }
                    }
                } else if (data.status === 'error' || data.status === 'unknown') {
                    failAndClear(kind, data);
                }
            } catch {
                failAndClear(kind, null);
            } finally {
                inFlightRef.current.delete(taskId);
            }
        };

        const tick = () => {
            const workoutTask = window.localStorage.getItem(WORKOUT_TASK_KEY);
            const dietTask = window.localStorage.getItem(DIET_TASK_KEY);
            if (workoutTask) {
                void pollTask(workoutTask, 'workout');
            }
            if (dietTask) {
                void pollTask(dietTask, 'diet');
            }
        };

        if (pollRef.current) {
            clearInterval(pollRef.current);
        }
        tick();
        pollRef.current = window.setInterval(tick, 2000);

        return () => {
            if (pollRef.current) {
                clearInterval(pollRef.current);
                pollRef.current = null;
            }
        };
    }, [navigate, location.pathname]);

    return null;
};

type ProfileGate = 'loading' | 'ready' | 'missing';

const GenerationFailureHandler: React.FC<{ onFailure: (payload: GenerationFailurePayload) => void }> = ({
    onFailure
}) => {
    const navigate = useNavigate();
    const location = useLocation();
    const lastFailureRef = useRef<string | null>(null);

    useEffect(() => {
        const getStoredLang = () => {
            try {
                return window.sessionStorage.getItem(LANG_STORAGE_KEY) ?? '';
            } catch {
                return '';
            }
        };

        const buildQuery = (): string => {
            const params = new URLSearchParams();
            const storedLang = getStoredLang();
            if (storedLang) {
                params.set('lang', storedLang);
            }
            const query = params.toString();
            return query ? `?${query}` : '';
        };

        const handler = (event: Event) => {
            const payload = (event as CustomEvent<GenerationFailurePayload>).detail;
            if (!payload) {
                return;
            }
            const dedupeKey = `${payload.feature}:${payload.errorCode ?? 'na'}:${payload.correlationId ?? 'na'}`;
            if (lastFailureRef.current === dedupeKey) {
                return;
            }
            lastFailureRef.current = dedupeKey;
            const query = buildQuery();
            const target = payload.feature === 'diets' ? `/diets${query}` : `/${query}`;
            if (location.pathname !== (payload.feature === 'diets' ? '/diets' : '/')) {
                navigate(target, { replace: true });
            }
            onFailure(payload);
        };
        window.addEventListener(GENERATION_FAILED_EVENT, handler as EventListener);
        return () => {
            window.removeEventListener(GENERATION_FAILED_EVENT, handler as EventListener);
        };
    }, [navigate, location.pathname, onFailure]);

    return null;
};

const App: React.FC = () => {
    useTelegramInit();
    const [profileGate, setProfileGate] = useState<ProfileGate>('loading');
    const initData = useMemo(() => readInitData(), []);
    const [langVersion, setLangVersion] = useState(0);
    const [generationFailure, setGenerationFailure] = useState<GenerationFailurePayload | null>(null);

    useEffect(() => {
        if (!initData) {
            setProfileGate('missing');
            return;
        }
        let active = true;
        const controller = new AbortController();

        const loadProfile = async () => {
            try {
                const profile = await getProfile(initData, controller.signal);
                if (!active) return;
                console.info('webapp.profile.language', { language: profile.language });
                await applyLang(profile.language ?? undefined);
                if (!active) return;
                if (profile.status !== 'completed') {
                    setProfileGate('missing');
                    return;
                }
                setProfileGate('ready');
            } catch (err) {
                if (!active) return;
                if (err instanceof HttpError && err.status === 404) {
                    setProfileGate('missing');
                    return;
                }
                setProfileGate('ready');
            }
        };

        void loadProfile();

        return () => {
            active = false;
            controller.abort();
        };
    }, [initData]);

    useEffect(() => {
        const handleLangChange = () => {
            setLangVersion((prev) => prev + 1);
        };
        window.addEventListener(LANG_CHANGED_EVENT, handleLangChange);
        return () => {
            window.removeEventListener(LANG_CHANGED_EVENT, handleLangChange);
        };
    }, []);

    if (profileGate === 'missing') {
        return <RegistrationRequiredPage />;
    }

    if (profileGate === 'loading') {
        return (
            <div className="registration-gate__loading" aria-live="polite" aria-busy="true">
                <span className="button-spinner" aria-hidden="true" />
            </div>
        );
    }
    return (
        <BrowserRouter>
            <LegacyRedirect />
            <GlobalGenerationRedirect />
            <GenerationFailureHandler onFailure={setGenerationFailure} />
            <Routes key={langVersion}>
                <Route path="/" element={<ProgramPage />} />
                <Route path="/history" element={<HistoryPage />} />
                <Route path="/payment" element={<PaymentPage />} />
                <Route path="/topup" element={<TopupPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="/faq" element={<FaqPage />} />
                <Route path="/weekly-survey" element={<WeeklySurveyPage />} />
                <Route path="/workout-flow" element={<WorkoutFlowPage />} />
                <Route path="/diets" element={<DietPage />} />
                <Route path="/diet-flow" element={<DietFlowPage />} />
            </Routes>
            {generationFailure && (
                <GenerationFailedModal
                    payload={generationFailure}
                    initData={initData}
                    onClose={() => setGenerationFailure(null)}
                />
            )}
        </BrowserRouter>
    );
};

export default App;

import React, { useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useSearchParams } from 'react-router-dom';
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
import { useTelegramInit } from './hooks/useTelegramInit';
import { getProfile, HttpError } from './api/http';
import { readInitData } from './telegram';

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

type ProfileGate = 'loading' | 'ready' | 'missing';

const App: React.FC = () => {
    useTelegramInit();
    const [profileGate, setProfileGate] = useState<ProfileGate>('loading');
    const initData = useMemo(() => readInitData(), []);

    useEffect(() => {
        if (!initData) {
            setProfileGate('missing');
            return;
        }
        let active = true;
        const controller = new AbortController();

        getProfile(initData, controller.signal)
            .then((profile) => {
                if (!active) return;
                if (profile.status !== 'completed') {
                    setProfileGate('missing');
                    return;
                }
                setProfileGate('ready');
            })
            .catch((err) => {
                if (!active) return;
                if (err instanceof HttpError && err.status === 404) {
                    setProfileGate('missing');
                    return;
                }
                setProfileGate('ready');
            });

        return () => {
            active = false;
            controller.abort();
        };
    }, [initData]);

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
            <Routes>
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
        </BrowserRouter>
    );
};

export default App;

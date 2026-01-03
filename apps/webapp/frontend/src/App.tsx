import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useSearchParams } from 'react-router-dom';
import ProgramPage from './pages/ProgramPage';
import HistoryPage from './pages/HistoryPage';
import PaymentPage from './pages/PaymentPage';
import TopupPage from './pages/TopupPage';
import FaqPage from './pages/FaqPage';
import WeeklySurveyPage from './pages/WeeklySurveyPage';
import ProfilePage from './pages/ProfilePage';
import { useTelegramInit } from './hooks/useTelegramInit';

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
        } else if (type === 'program') {
            navigate(withSearch('/'), { replace: true });
        }
    }, [searchParams, navigate]);

    return null;
};

const App: React.FC = () => {
    useTelegramInit();
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
            </Routes>
        </BrowserRouter>
    );
};

export default App;

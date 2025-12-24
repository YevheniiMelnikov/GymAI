import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useSearchParams } from 'react-router-dom';
import ProgramPage from './pages/ProgramPage';
import HistoryPage from './pages/HistoryPage';
import PaymentPage from './pages/PaymentPage';
import FaqPage from './pages/FaqPage';
import { useTelegramInit } from './hooks/useTelegramInit';

const PAYMENT_ORDER_KEY = 'webapp:payment:order_id';

// Component to handle legacy query params redirection
const LegacyRedirect = () => {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();

    useEffect(() => {
        const params = new URLSearchParams(searchParams);
        const type = params.get('type');
        const orderId = params.get('order_id') ?? params.get('orderId');
        if (orderId) {
            try {
                sessionStorage.setItem(PAYMENT_ORDER_KEY, orderId);
            } catch {
            }
        } else {
            try {
                sessionStorage.removeItem(PAYMENT_ORDER_KEY);
            } catch {
            }
        }
        params.delete('type');
        const search = params.toString();
        const withSearch = (path: string) => (search ? `${path}?${search}` : path);

        if (type === 'history') {
            navigate(withSearch('/history'), { replace: true });
        } else if (type === 'payment') {
            navigate(withSearch('/payment'), { replace: true });
        } else if (type === 'faq') {
            navigate(withSearch('/faq'), { replace: true });
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
                <Route path="/faq" element={<FaqPage />} />
            </Routes>
        </BrowserRouter>
    );
};

export default App;

import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useSearchParams } from 'react-router-dom';
import ProgramPage from './pages/ProgramPage';
import HistoryPage from './pages/HistoryPage';
import PaymentPage from './pages/PaymentPage';

// Component to handle legacy query params redirection
const LegacyRedirect = () => {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();

    useEffect(() => {
        const type = searchParams.get('type');
        if (type === 'history') {
            navigate('/history', { replace: true });
        } else if (type === 'payment') {
            navigate('/payment', { replace: true });
        } else if (type === 'program') {
            navigate('/', { replace: true });
        }
    }, [searchParams, navigate]);

    return null;
};

const App: React.FC = () => {
    return (
        <BrowserRouter>
            <LegacyRedirect />
            <Routes>
                <Route path="/" element={<ProgramPage />} />
                <Route path="/history" element={<HistoryPage />} />
                <Route path="/payment" element={<PaymentPage />} />
            </Routes>
        </BrowserRouter>
    );
};

export default App;

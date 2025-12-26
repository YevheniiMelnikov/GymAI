import React, { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { applyLang } from '../i18n/i18n';

const WeeklySurveyPage: React.FC = () => {
    const [searchParams] = useSearchParams();
    const paramLang = searchParams.get('lang') || undefined;

    useEffect(() => {
        void applyLang(paramLang);
    }, [paramLang]);

    return <div className="page-container" />;
};

export default WeeklySurveyPage;

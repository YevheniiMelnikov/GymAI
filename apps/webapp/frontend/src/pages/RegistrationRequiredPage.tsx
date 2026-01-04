import React from 'react';
import { closeWebApp } from '../telegram';

const RegistrationRequiredPage: React.FC = () => {
    return (
        <section className="registration-gate">
            <div className="registration-gate__card">
                <p className="registration-gate__eyebrow">GymBot</p>
                <h1 className="registration-gate__title">Завершіть створення профілю</h1>
                <p className="registration-gate__text">
                    Щоб відкрити вебзастосунок, спочатку пройдіть коротку реєстрацію в боті.
                </p>
                <div className="registration-gate__steps">
                    <div className="registration-gate__step">1. Оберіть мову</div>
                    <div className="registration-gate__step">2. Вкажіть рік народження та стать</div>
                    <div className="registration-gate__step">3. Заповніть базові дані про тренування</div>
                </div>
                <button type="button" className="primary-button registration-gate__button" onClick={closeWebApp}>
                    Повернутися до бота
                </button>
            </div>
            <p className="registration-gate__hint">
                Після завершення анкети доступ до тренувань та профілю відкриється автоматично.
            </p>
        </section>
    );
};

export default RegistrationRequiredPage;

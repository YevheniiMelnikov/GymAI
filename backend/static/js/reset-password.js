document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('reset-password-form');
    form.addEventListener('submit', handleResetPassword);

    async function handleResetPassword(event) {
        event.preventDefault();

        const newPassword = document.getElementById('new-password').value;
        const confirmPassword = document.getElementById('confirm-password').value;

        if (newPassword !== confirmPassword) {
            alert('Пароли не совпадают');
            return;
        }

        const pathArray = window.location.pathname.split('/');
        const uid = pathArray[2];
        const token = pathArray[3];
        const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;

        try {
            const response = await fetch('/api/v1/auth/users/reset_password_confirm/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrftoken
                },
                body: JSON.stringify({
                    uid: uid,
                    token: token,
                    new_password: newPassword,
                    re_new_password: confirmPassword
                })
            });

            // Если статус ответа 204, ничего не читаем из тела ответа
            if (response.status === 204) {
                alert('Пароль успешно сброшен');
                window.location.href = 'https://t.me/my_another_useless_test_bot';
            } else if (response.ok) {
                // Если ответ успешный, но статус не 204, пытаемся прочитать JSON
                const responseData = await response.json();
                // Обработка полученных данных...
            } else {
                // Если ответ не успешный, пытаемся прочитать и обработать ошибку из JSON
                try {
                    const responseData = await response.json();
                    const error = responseData.non_field_errors || 'Произошла ошибка при сбросе пароля';
                    alert(error);
                    console.error('Error resetting password:', error);
                } catch (jsonError) {
                    // Если не удалось прочитать JSON, выводим общее сообщение об ошибке
                    console.error('Error reading response:', jsonError);
                    alert('Произошла ошибка при сбросе пароля');
                }
            }
        } catch (networkError) {
            // Обработка сетевых ошибок или других исключений
            console.error('Network or other error:', networkError);
            alert('Ошибка сети или другая ошибка');
        }
    }
});

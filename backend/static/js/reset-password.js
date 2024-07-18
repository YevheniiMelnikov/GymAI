document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('reset-password-form');
    form.addEventListener('submit', handleResetPassword);

    async function handleResetPassword(event) {
        event.preventDefault();

        const newPassword = document.getElementById('new-password').value;
        const confirmPassword = document.getElementById('confirm-password').value;

        if (newPassword !== confirmPassword) {
            alert('Паролі не співпадають');
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

            if (response.status === 204) {
                alert('Пароль успішно скинуто');
                window.location.href = 'https://t.me/achieve_together_bot';
            } else {
                const responseData = await response.json();
                if (response.ok) {
                } else {
                    if (responseData.password) {
                        alert('Пароль не відповідає критеріям безпеки: ' + responseData.password.join(' '));
                    } else {
                        const error = responseData.non_field_errors || 'Відбулась помилка під час скидання пароля';
                        alert(error);
                        console.error('Error resetting password:', error);
                    }
                }
            }
        } catch (networkError) {
            console.error('Network or other error:', networkError);
            alert('Виникла непередбачена помилка');
        }
    }
});

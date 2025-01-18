from djoser.email import PasswordResetEmail


class CustomPasswordResetEmail(PasswordResetEmail):
    template_name = "email/password_reset.html"
    html_email_template_name = "email/password_reset.html"

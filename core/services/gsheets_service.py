from __future__ import annotations

from datetime import datetime
from typing import List

from config.app_settings import settings


class GSheetsService:
    SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
    DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
    creds_path = settings.GOOGLE_APPLICATION_CREDENTIALS
    sheet_id = settings.SPREADSHEET_ID

    @classmethod
    def _connect(cls):
        """Create an authorised gspread client.

        The heavy ``gspread`` and ``google.oauth2`` imports are performed lazily so
        that test environments without these optional dependencies can import this
        module without raising errors.  At runtime these packages are expected to
        be available.
        """

        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            cls.creds_path,
            scopes=[cls.SHEETS_SCOPE, cls.DRIVE_SCOPE],
        )
        return gspread.authorize(creds)

    @classmethod
    def create_new_payment_sheet(cls, data: List[List[str]]):
        client = cls._connect()
        spreadsheet = client.open_by_key(cls.sheet_id)

        sheet_name = datetime.now().strftime("%Y-%m-%d")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=len(data) + 10, cols=10)

        worksheet.append_row(
            ["Имя", "Фамилия", "Номер карты", "Order ID", "Сумма к зачислению"],
            value_input_option="USER_ENTERED",  # pyrefly: ignore[bad-argument-type]
        )
        if data:
            worksheet.append_rows(data, value_input_option="USER_ENTERED")  # pyrefly: ignore[bad-argument-type]

        return worksheet

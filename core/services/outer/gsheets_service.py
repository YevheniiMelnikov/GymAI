from datetime import datetime
from typing import List

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption

from config.env_settings import Settings


class GSheetsService:
    SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
    DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
    creds_path = Settings.GOOGLE_APPLICATION_CREDENTIALS
    sheet_id = Settings.SPREADSHEET_ID

    @classmethod
    def _connect(cls) -> gspread.Client:
        creds = Credentials.from_service_account_file(
            cls.creds_path,
            scopes=[cls.SHEETS_SCOPE, cls.DRIVE_SCOPE],
        )
        return gspread.authorize(creds)

    @classmethod
    def create_new_payment_sheet(cls, data: List[List[str]]) -> gspread.Worksheet:
        client = cls._connect()
        spreadsheet = client.open_by_key(cls.sheet_id)

        sheet_name = datetime.now().strftime("%Y-%m-%d")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=len(data) + 10, cols=10)

        worksheet.append_row(
            ["Имя", "Фамилия", "Номер карты", "Order ID", "Сумма к зачислению"],
            value_input_option=ValueInputOption.user_entered,
        )
        if data:
            worksheet.append_rows(data, value_input_option=ValueInputOption.user_entered)

        return worksheet

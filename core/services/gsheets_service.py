from datetime import datetime
from typing import List

import gspread
from google.oauth2.service_account import Credentials

from config.app_settings import settings


class GSheetsService:
    SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
    DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
    creds_path = settings.GOOGLE_APPLICATION_CREDENTIALS
    sheet_id = settings.SPREADSHEET_ID

    @classmethod
    def create_new_payment_sheet(cls, data: List[List[str]]):
        creds = Credentials.from_service_account_file(
            cls.creds_path,
            scopes=[cls.SHEETS_SCOPE, cls.DRIVE_SCOPE],
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(cls.sheet_id)

        sheet_name = datetime.now().strftime("%Y-%m-%d")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=len(data) + 10, cols=10)

        worksheet.append_row(
            ["Имя", "Фамилия", "Номер карты", "Order ID", "Сумма к зачислению"],
            value_input_option="USER_ENTERED",
        )
        if data:
            worksheet.append_rows(data, value_input_option="USER_ENTERED")

        return worksheet

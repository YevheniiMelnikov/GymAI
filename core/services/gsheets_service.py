from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from gspread import Worksheet

from config.env_settings import Settings


class GSheetsService:
    SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
    DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
    creds = Settings.GOOGLE_APPLICATION_CREDENTIALS
    sheet_id = Settings.SPREADSHEET_ID

    @classmethod
    def connect(cls) -> gspread.Client:
        creds = Credentials.from_service_account_file(cls.creds, scopes=[cls.SHEETS_SCOPE, cls.DRIVE_SCOPE])
        return gspread.authorize(creds)

    @classmethod
    def create_new_payment_sheet(cls, data: list[list]) -> Worksheet:
        client = cls.connect()
        spreadsheet = client.open_by_key(cls.sheet_id)
        sheet_name = datetime.now().strftime("%Y-%m-%d")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=100, cols=10)
        worksheet.append_row(["Имя", "Фамилия", "Номер карты", "Order ID", "Сумма к зачислению"])
        worksheet.append_rows(data)
        return worksheet

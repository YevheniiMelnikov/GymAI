import os
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from gspread import Worksheet

from common.decorators import singleton


@singleton
class SheetsManager:
    def __init__(self) -> None:
        self.creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.sheet_id = os.getenv("SPREADSHEET_ID")

    def connect(self) -> gspread.Client:
        creds = Credentials.from_service_account_file(
            self.creds, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )
        return gspread.authorize(creds)

    def create_new_payment_sheet(self, data: list[list]) -> Worksheet:
        client = self.connect()
        spreadsheet = client.open_by_key(self.sheet_id)
        sheet_name = datetime.now().strftime("%Y-%m-%d")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=100, cols=10)
        worksheet.append_row(["Имя", "Фамилия", "Номер карты", "Order ID", "Сумма к зачислению"])
        worksheet.append_rows(data)
        return worksheet


sheets_manager = SheetsManager()

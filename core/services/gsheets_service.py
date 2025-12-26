from datetime import datetime
from typing import List

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption
from gspread.exceptions import WorksheetNotFound

from config.app_settings import settings


class GSheetsService:
    SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
    DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
    creds_path = settings.GOOGLE_APPLICATION_CREDENTIALS
    sheet_id = settings.SPREADSHEET_ID

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

    @classmethod
    def append_weekly_metrics(cls, row: list[str]) -> gspread.Worksheet:
        if not settings.SPREADSHEET_ID:
            raise ValueError("SPREADSHEET_ID is not configured")
        client = cls._connect()
        spreadsheet = client.open_by_key(cls.sheet_id)
        sheet_title = "Weekly Metrics"
        try:
            worksheet = spreadsheet.worksheet(sheet_title)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=sheet_title, rows=100, cols=10)
            worksheet.append_row(
                [
                    "period_start",
                    "period_end",
                    "new_users",
                    "diet_plans",
                    "ask_ai_answers",
                    "workout_plans",
                    "payments_total",
                ],
                value_input_option=ValueInputOption.user_entered,
            )
        worksheet.append_row(row, value_input_option=ValueInputOption.user_entered)
        return worksheet

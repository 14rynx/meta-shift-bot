import json

from apiclient import discovery
from google.oauth2 import service_account

# The ID and range of a sample spreadsheet.
with open('secrets.json', "r") as f:
    SPREADSHEET_ID = json.loads(f.read())["SPREADSHEET_ID"]


class SpreadsheetConnector:
    def __init__(self):
        scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
                  "https://www.googleapis.com/auth/spreadsheets"]
        credentials = service_account.Credentials.from_service_account_file("credentials.json", scopes=scopes)
        self.service = discovery.build('sheets', 'v4', credentials=credentials)
        self.sheet = self.service.spreadsheets()

    def get_ids(self, season_id):
        result = self.sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'Season {season_id}!A1:A').execute()
        return result.get('values', [])

    def add_update(self, season_id: int, target_entry_id: str, data: list):
        entry_ids = self.get_ids(season_id)

        target_column = None
        for i, entry_id in enumerate(entry_ids):
            if target_entry_id == entry_id[0]:
                target_column = i + 1
        if not target_column:
            target_column = len(entry_ids) + 1

        body = {'values': [[target_entry_id] + data]}
        start = "A"
        end = chr(ord(start) + len(data) + 1)
        self.service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f'Season {season_id}!{start}{target_column}:{end}{target_column}',
            valueInputOption="USER_ENTERED", body=body
        ).execute()

        return "added" if not target_column else "updated"

    def add_season(self, season_id):
        body = {'requests': [{'addSheet': {'properties': {'title': f"Season {season_id}"}}}]}
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID, body=body
        ).execute()

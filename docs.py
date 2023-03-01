import json
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# The ID and range of a sample spreadsheet.
with open('secrets.json', "r") as f:
    SPREADSHEET_ID = json.loads(f.read())["SPREADSHEET_ID"]


class SpreadsheetConnector:
    def __init__(self):
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        self.service = build('sheets', 'v4', credentials=creds)
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

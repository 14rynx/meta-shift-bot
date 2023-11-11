import json
from datetime import datetime, timedelta

from apiclient import discovery
from google.oauth2 import service_account

from utils import get_item_name

# The ID and range of a sample spreadsheet.
with open('secrets.json', "r") as f:
    SPREADSHEET_ID = json.loads(f.read())["SPREADSHEET_ID"]


class RulesConnector:
    def __init__(self, season_id):
        self.season_id = season_id

        self._rarity_adjusted_missing = set()
        self._risk_adjusted_missing = set()
        self._missing = set()

        self._rarity_adjusted_points = {}
        self._risk_adjusted_points = {}
        self._points = {}

        self.last_updated = None

    async def update(self, session):
        if self.last_updated is None or self.last_updated < datetime.now() - timedelta(minutes=5):
            self.last_updated = datetime.now()

            scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
                      "https://www.googleapis.com/auth/spreadsheets"]
            credentials = service_account.Credentials.from_service_account_file("../credentials.json", scopes=scopes)
            service = discovery.build('sheets', 'v4', credentials=credentials)
            sheet = service.spreadsheets()

            self._rarity_adjusted_points = self._get_points(sheet, "A")
            self._risk_adjusted_points = self._get_points(sheet, "E")
            self._points = self._get_points(sheet, "I")

            await self._write_back(session, sheet, service, "A", self._rarity_adjusted_missing)
            await self._write_back(session, sheet, service, "E", self._risk_adjusted_missing)
            await self._write_back(session, sheet, service, "I", self._missing)

            self._rarity_adjusted_missing = set()
            self._risk_adjusted_missing = set()
            self._missing = set()

            service.close()

    def _get_points(self, sheet, start):

        end = chr(ord(start) + 1)
        _range = f'Season {self.season_id}!{start}3:{end}'
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=_range).execute()
        values = result.get('values', [])

        out = {}
        for line in values:
            try:
                item_id, point_value = line
                point_value = float(point_value.replace(",", "."))
                item_id = int(item_id)
            except ValueError:
                continue
            else:
                out[item_id] = point_value
        return out

    async def _write_back(self, session, sheet, service, start, type_ids):
        body = {'values': [[type_id, "TODO", await get_item_name(session, type_id)] for type_id in type_ids]}

        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                    range=f'Season {self.season_id}!{start}3:{start}').execute()
        values = result.get('values', [])
        start_column = len(values) + 3
        end_column = len(body["values"]) + start_column - 1

        end = chr(ord(start) + 3)

        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Season {self.season_id}!{start}{start_column}:{end}{end_column}',
            valueInputOption="USER_ENTERED", body=body
        ).execute()

    def rarity_adjusted_points(self, type_id):
        try:
            return self._rarity_adjusted_points[type_id]
        except KeyError:
            self._rarity_adjusted_missing.add(type_id)
            return None

    def risk_adjusted_points(self, type_id):
        try:
            return self._risk_adjusted_points[type_id]
        except KeyError:
            self._risk_adjusted_missing.add(type_id)
            return None

    def points(self, type_id):
        try:
            return self._points[type_id]
        except KeyError:
            self._missing.add(type_id)
            return None

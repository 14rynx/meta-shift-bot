import json
import ssl
from datetime import datetime, timedelta

import aiohttp
import certifi
from apiclient import discovery
from google.oauth2 import service_account

# The ID and range of a sample spreadsheet.
with open('secrets.json', "r") as f:
    SPREADSHEET_ID = json.loads(f.read())["SPREADSHEET_ID"]


async def get_item_name(type_id):
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(f"https://esi.evetech.net/latest/universe/types/{type_id}/") as response:
            if response.status == 200:
                return (await response.json(content_type=None))["name"]
            return f"Could not Fetch Item Name, Type ID: {type_id}"


class RulesConnector:
    def __init__(self, season_id):
        self.season_id = season_id

        self._victim_missing = set()
        self._killer_missing = set()
        self._helper_missing = set()

        self._victim_points = {}
        self._killer_points = {}
        self._helper_points = {}

        self.kill_formula = "0"
        self.sum_formula = "0"

        self.last_updated = None

    async def update(self):
        if self.last_updated is None or self.last_updated < datetime.now() - timedelta(minutes=5):
            self.last_updated = datetime.now()

            scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
                      "https://www.googleapis.com/auth/spreadsheets"]
            credentials = service_account.Credentials.from_service_account_file("../credentials.json", scopes=scopes)
            service = discovery.build('sheets', 'v4', credentials=credentials)
            sheet = service.spreadsheets()

            self._victim_points = self.get_points(sheet, "A")
            self._killer_points = self.get_points(sheet, "E")
            self._helper_points = self.get_points(sheet, "I")

            result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'Season {self.season_id}!M2:M2').execute()
            self.kill_formula = result.get('values', [])[0][0]

            result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'Season {self.season_id}!O2:O2').execute()
            self.sum_formula = result.get('values', [])[0][0]

            body = {'values': [[type_id, "TODO", await get_item_name(type_id)] for type_id in self._victim_missing]}
            self.write_back(sheet, service, "A", body)
            body = {'values': [[type_id, "TODO", await get_item_name(type_id)] for type_id in self._killer_missing]}
            self.write_back(sheet, service, "E", body)
            body = {'values': [[type_id, "TODO", await get_item_name(type_id)] for type_id in self._helper_missing]}
            self.write_back(sheet, service, "I", body)

            self._victim_missing = set()
            self._killer_missing = set()
            self._helper_missing = set()
            service.close()

    def get_points(self, sheet, start):

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

    def write_back(self, sheet, service, start, body):
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

    def victim_points(self, type_id):
        try:
            return self._victim_points[type_id]
        except KeyError:
            self._victim_missing.add(type_id)

    def killer_points(self, type_id):
        try:
            return self._killer_points[type_id]
        except KeyError:
            self._killer_missing.add(type_id)

    def helper_points(self, type_id):
        try:
            return self._helper_points[type_id]
        except KeyError:
            self._helper_missing.add(type_id)

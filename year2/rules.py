import json
import ssl

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
        scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
                  "https://www.googleapis.com/auth/spreadsheets"]
        credentials = service_account.Credentials.from_service_account_file("../credentials.json", scopes=scopes)
        self.service = discovery.build('sheets', 'v4', credentials=credentials)
        self.sheet = self.service.spreadsheets()

        self._victim_points = self.get_points("A")
        self._killer_points = self.get_points("E")
        self._helper_points = self.get_points("I")

        self._victim_missing = set()
        self._killer_missing = set()
        self._helper_missing = set()

        result = self.sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'Season {self.season_id}!M2:M2').execute()
        self.kill_formula = result.get('values', [])[0][0]

        result = self.sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'Season {self.season_id}!O2:O2').execute()
        self.sum_formula = result.get('values', [])[0][0]

        print(self._killer_points, self._victim_points, self._helper_points, self.kill_formula, self.sum_formula)

    def get_points(self, start):

        end = chr(ord(start) + 1)
        _range = f'Season {self.season_id}!{start}3:{end}'
        result = self.sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=_range).execute()
        values = result.get('values', [])

        out = {}
        for k, v in values:
            try:
                v = float(v)
                k = int(k)
            except ValueError:
                continue
            else:
                out[k] = v
        return out

    def writeback_row(self, start, body):
        result = self.sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                         range=f'Season {self.season_id}!{start}3:{start}').execute()
        values = result.get('values', [])
        start_column = len(values) + 3
        end_column = len(body["values"]) + start_column - 1

        end = chr(ord(start) + 3)

        self.service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Season {self.season_id}!{start}{start_column}:{end}{end_column}',
            valueInputOption="USER_ENTERED", body=body
        ).execute()

    async def writeback(self):
        body = {'values': [[type_id, "TODO", await get_item_name(type_id)] for type_id in self._victim_missing]}
        self.writeback_row("A", body)
        body = {'values': [[type_id, "TODO", await get_item_name(type_id)] for type_id in self._killer_missing]}
        self.writeback_row("E", body)
        body = {'values': [[type_id, "TODO", await get_item_name(type_id)] for type_id in self._helper_missing]}
        self.writeback_row("I", body)

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

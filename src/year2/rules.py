import os
from datetime import datetime, timedelta

from apiclient import discovery
from google.oauth2 import service_account

from network import get_item_name


class PointColumn:
    def __init__(self, location):
        self.values = {}
        self.location = location
        self.unknown_values = set()
        self.missing = set()

    def __call__(self, kill_fragment):
        type_id = kill_fragment.get("ship_type_id", 0)
        try:
            return self.values[type_id]
        except KeyError:
            if type_id not in self.unknown_values:
                self.missing.add(type_id)
            return None

    def fetch(self, season, sheet):
        """Fetch and parse one set of points from a spreadsheet"""
        end = chr(ord(self.location) + 1)
        _range = f'{season.name}!{self.location}3:{end}'
        result = sheet.values().get(spreadsheetId=os.environ["SPREADSHEET_ID"], range=_range).execute()
        values = result.get('values', [])

        for line in values:
            try:
                item_id, point_value = line
                item_id = int(item_id)
            except ValueError:
                continue
            else:
                try:
                    point_value = float(point_value.replace(",", "."))
                except ValueError:
                    self.unknown_values.add(item_id)
                else:
                    self.values[item_id] = point_value

    async def write_back(self, season, sheet, session):
        """For any values that could not be found, add a new entry to the spreadsheet"""
        body = {'values': [[type_id, "TODO", await get_item_name(session, type_id)] for type_id in self.missing]}

        result = sheet.values().get(spreadsheetId=os.environ["SPREADSHEET_ID"],
                                    range=f'{season.name}!{self.location}3:{self.location}').execute()
        values = result.get('values', [])
        start_column = len(values) + 3
        end_column = len(body["values"]) + start_column - 1

        end = chr(ord(self.location) + 3)

        sheet.values().update(
            spreadsheetId=os.environ["SPREADSHEET_ID"],
            range=f'{season.name}!{self.location}{start_column}:{end}{end_column}',
            valueInputOption="USER_ENTERED", body=body
        ).execute()

        self.missing = set()

    async def update(self, season, sheet, session):
        """Fetch and write back"""
        self.fetch(season, sheet)
        await self.write_back(season, sheet, session)


class RulesConnector:
    def __init__(self, season):
        self.season = season

        self.base = PointColumn("A")
        self.rarity_adjusted = PointColumn("E")
        self.risk_adjusted = PointColumn("I")
        self.time_adjusted = PointColumn("M")

        self.last_updated = None

    async def update(self, session):
        if self.last_updated is None or self.last_updated < datetime.now() - timedelta(minutes=5):
            self.last_updated = datetime.now()

            scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/drive.file",
                      "https://www.googleapis.com/auth/spreadsheets"]
            credentials = service_account.Credentials.from_service_account_file("credentials.json", scopes=scopes)
            service = discovery.build('sheets', 'v4', credentials=credentials)
            sheet = service.spreadsheets()

            await self.base.update(self.season, sheet, session)
            await self.rarity_adjusted.update(self.season, sheet, session)
            await self.risk_adjusted.update(self.season, sheet, session)
            await self.time_adjusted.update(self.season, sheet, session)

            service.close()

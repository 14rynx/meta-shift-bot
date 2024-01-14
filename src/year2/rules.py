import os
from datetime import datetime, timedelta

from apiclient import discovery
from google.oauth2 import service_account

from network import get_item_name


class PointColumn:
    def __init__(self, location):
        self.values = {}
        self.location = location
        self.missing = set()

    def __call__(self, type_id):
        try:
            return self.values[type_id]
        except KeyError:
            self.missing.add(type_id)
            return None

    def fetch(self, season_id, sheet):
        """Fetch and parse one set of points from a spreadsheet"""
        end = chr(ord(self.location) + 1)
        _range = f'Season {season_id}!{self.location}3:{end}'
        result = sheet.values().get(spreadsheetId=os.environ["SPREADSHEET_ID"], range=_range).execute()
        values = result.get('values', [])

        for line in values:
            try:
                item_id, point_value = line
                point_value = float(point_value.replace(",", "."))
                item_id = int(item_id)
            except ValueError:
                continue
            else:
                self.values[item_id] = point_value

    async def write_back(self, season_id, sheet, session):
        """For any values that could not be found, add a new entry to the spreadsheet"""
        body = {'values': [[type_id, "TODO", await get_item_name(session, type_id)] for type_id in self.missing]}

        result = sheet.values().get(spreadsheetId=os.environ["SPREADSHEET_ID"],
                                    range=f'Season {season_id}!{self.location}3:{self.location}').execute()
        values = result.get('values', [])
        start_column = len(values) + 3
        end_column = len(body["values"]) + start_column - 1

        end = chr(ord(self.location) + 3)

        sheet.values().update(
            spreadsheetId=os.environ["SPREADSHEET_ID"],
            range=f'Season {season_id}!{self.location}{start_column}:{end}{end_column}',
            valueInputOption="USER_ENTERED", body=body
        ).execute()

        self.missing = set()

    async def update(self, season_id, sheet, session):
        """Fetch and write back"""
        self.fetch(season_id, sheet)
        await self.write_back(season_id, sheet, session)


class RulesConnector:
    def __init__(self, season_id):
        self.season_id = season_id

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

            await self.base.update(self.season_id, sheet, session)
            await self.rarity_adjusted.update(self.season_id, sheet, session)
            await self.risk_adjusted.update(self.season_id, sheet, session)
            await self.time_adjusted.update(self.season_id, sheet, session)

            service.close()

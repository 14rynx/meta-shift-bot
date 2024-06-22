from peewee import *

# Initialize the database
db = SqliteDatabase('data/bot.db')


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    user_id = CharField(primary_key=True)


class Season(BaseModel):
    name = CharField(primary_key=True)


class Entry(BaseModel):
    user = ForeignKeyField(User, backref='entries')
    season = ForeignKeyField(Season, backref='entries')
    character_id = CharField()
    relinks = IntegerField()
    points = FloatField()
    points_expiry = DateTimeField()


def initialize_database():
    with db:
        db.create_tables([User, Season, Entry])

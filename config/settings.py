from .app import AppSettings
from .auth import AuthSettings
from .blueprint import BlueprintSettings
from .database import DatabaseSettings
from .people import PeopleSettings
from .review import ReviewSettings
from .teams import TeamsSettings


class Settings:
    app = AppSettings()
    auth = AuthSettings()
    db = DatabaseSettings()
    blueprint = BlueprintSettings()
    review = ReviewSettings()
    people = PeopleSettings()
    teams = TeamsSettings()


settings = Settings()

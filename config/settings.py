from .app import AppSettings
from .auth import AuthSettings
from .blueprint import BlueprintSettings
from .database import DatabaseSettings
from .review import ReviewSettings


class Settings:
    app = AppSettings()
    auth = AuthSettings()
    db = DatabaseSettings()
    blueprint = BlueprintSettings()
    review = ReviewSettings()


settings = Settings()

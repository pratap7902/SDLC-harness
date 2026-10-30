from .app import AppSettings
from .auth import AuthSettings
from .azure_devops import AzureDevOpsSettings
from .blueprint import BlueprintSettings
from .database import DatabaseSettings
from .github import GithubSettings
from .knowledge import KnowledgeSettings
from .people import PeopleSettings
from .review import ReviewSettings
from .teams import TeamsSettings


class Settings:
    app = AppSettings()
    auth = AuthSettings()
    db = DatabaseSettings()
    blueprint = BlueprintSettings()
    review = ReviewSettings()
    github = GithubSettings()
    people = PeopleSettings()
    teams = TeamsSettings()
    knowledge = KnowledgeSettings()
    azure_devops = AzureDevOpsSettings()


settings = Settings()

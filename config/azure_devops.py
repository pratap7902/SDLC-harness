from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureDevOpsSettings(BaseSettings):
    """Azure DevOps Boards (REST API, PAT auth). Org, project, PAT and the webhook secret
    come from the environment; nothing tenant-specific is in the code. Empty ADO_ORG or
    ADO_PAT → the integration is off."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ADO_BASE_URL: str = Field(default="https://dev.azure.com", validation_alias="ADO_BASE_URL")
    ADO_ORG: str = Field(default="", validation_alias="ADO_ORG")
    ADO_PROJECT: str = Field(default="", validation_alias="ADO_PROJECT")
    ADO_PAT: str = Field(default="", validation_alias="ADO_PAT")
    ADO_API_VERSION: str = Field(default="7.1", validation_alias="ADO_API_VERSION")
    # Service hook (Web Hooks consumer): sent as the X-SRS-Hook-Secret header, or as the
    # basic-auth password. Empty → the webhook refuses everything.
    ADO_WEBHOOK_SECRET: str = Field(default="", validation_alias="ADO_WEBHOOK_SECRET")
    # Which work item fields name the DRI and the engineering owner (identity fields; the
    # person is matched by email in the people directory). Empty → not taken from ADO.
    ADO_DRI_FIELD: str = Field(default="System.AssignedTo", validation_alias="ADO_DRI_FIELD")
    ADO_ENGG_FIELD: str = Field(default="", validation_alias="ADO_ENGG_FIELD")
    # The work item type pushed tasks become (a child of the imported item).
    ADO_CHILD_TYPE: str = Field(default="Task", validation_alias="ADO_CHILD_TYPE")

    def enabled(self) -> bool:
        return bool(self.ADO_ORG and self.ADO_PROJECT and self.ADO_PAT)

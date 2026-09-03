"""Configuration, read from the environment.

Twelve-factor rule: the SAME image runs in dev, staging and production, and
only the environment variables differ. Nothing here reads a config file and
nothing is baked into the image at build time — that is what lets the pipeline
build the artifact once and promote that one artifact through every stage.
"""

import os


class Settings:
    """Environment-driven settings, resolved once at import time."""

    def __init__(self) -> None:
        # Cosmetic, but they show up in / and in the logs, which makes it
        # obvious in the demo which build is actually running in the cluster.
        self.app_name: str = os.getenv("APP_NAME", "taskapi")
        self.environment: str = os.getenv("ENVIRONMENT", "local")

        # The pipeline injects the git SHA here (see the Kubernetes Deployment),
        # so `curl /` on a running pod tells you exactly which commit is live.
        self.release: str = os.getenv("RELEASE", "dev")

        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
        self.port: int = int(os.getenv("PORT", "8000"))

    def as_dict(self) -> dict[str, str | int]:
        return {
            "app_name": self.app_name,
            "environment": self.environment,
            "release": self.release,
            "log_level": self.log_level,
            "port": self.port,
        }


settings = Settings()

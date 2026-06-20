# src/services/github.py
from src.config import Settings

settings = Settings()


class GitHubClient:
    def __init__(self, installation_token: str | None = None):
        self.token = installation_token

    async def create_comment(self, repo: str, issue_number: int, body: str) -> dict:
        return {"url": f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments", "body": body}

    async def add_labels(self, repo: str, issue_number: int, labels: list[str]) -> dict:
        return {"labels": labels}

    async def create_pr(self, repo: str, title: str, head: str, base: str, body: str) -> dict:
        return {"number": 1, "url": f"https://github.com/{repo}/pull/1", "title": title}

    async def get_collaborator_permission(self, repo: str, username: str) -> str:
        return "write"

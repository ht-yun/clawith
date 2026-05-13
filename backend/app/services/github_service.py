"""GitHub service for OpenCode agents to manage repositories."""

import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx
from loguru import logger

class GitHubService:
    def __init__(self, pat: Optional[str] = None):
        self.pat = pat
        self.api_base = "https://api.github.com"

    async def _run_git(self, args: List[str], cwd: Path, env: Optional[Dict[str, str]] = None) -> str:
        """Helper to run git commands."""
        process = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **(env or {})}
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            # Mask PAT in error messages
            if self.pat:
                error_msg = error_msg.replace(self.pat, "***")
            raise Exception(f"Git error (code {process.returncode}): {error_msg}")
        return stdout.decode().strip()

    def _get_auth_url(self, repo_url: str) -> str:
        """Inject PAT into repo URL for authentication."""
        if not self.pat:
            return repo_url
        if "github.com" not in repo_url:
            return repo_url
        
        # https://github.com/user/repo -> https://pat@github.com/user/repo
        prefix = "https://"
        if repo_url.startswith(prefix):
            return f"{prefix}{self.pat}@{repo_url[len(prefix):]}"
        return repo_url

    async def clone(self, repo_url: str, target_dir: Path) -> str:
        """Clone a repository."""
        auth_url = self._get_auth_url(repo_url)
        if target_dir.exists() and any(target_dir.iterdir()):
             # If target exists, try pull instead or error?
             # For now, we assume target_dir is clean or handled by caller.
             pass
        
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        # git clone <url> <dir>
        return await self._run_git(["clone", auth_url, str(target_dir)], cwd=target_dir.parent)

    async def push(self, repo_dir: Path, branch: str = "main", message: str = "Update from OpenCode") -> str:
        """Add, commit and push changes."""
        await self._run_git(["add", "."], cwd=repo_dir)
        try:
            await self._run_git(["commit", "-m", message], cwd=repo_dir)
        except Exception as e:
            if "nothing to commit" in str(e).lower():
                return "Nothing to commit"
            raise e
        
        return await self._run_git(["push", "origin", branch], cwd=repo_dir)

    async def create_pr(self, repo_full_name: str, title: str, body: str, head: str, base: str = "main") -> Dict[str, Any]:
        """Create a Pull Request via GitHub API."""
        if not self.pat:
            raise Exception("GitHub PAT is required to create a Pull Request")
        
        url = f"{self.api_base}/repos/{repo_full_name}/pulls"
        headers = {
            "Authorization": f"token {self.pat}",
            "Accept": "application/vnd.github.v3+json"
        }
        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=data)
            if resp.status_code != 201:
                raise Exception(f"GitHub API error: {resp.text}")
            return resp.json()

github_service = GitHubService()

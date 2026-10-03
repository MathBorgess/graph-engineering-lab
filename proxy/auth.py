"""Credential readers shared by the two native proxies."""
import json
import logging
import os
import platform
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class ClaudeAuth:
    """Retrieves active OAuth token from macOS Keychain or ~/.claude/.credentials.json."""

    @staticmethod
    def get_token() -> str:
        if platform.system() == "Darwin":
            try:
                raw = subprocess.check_output(
                    ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                    stderr=subprocess.DEVNULL,
                ).decode().strip()
                data = json.loads(raw)
                token = data.get("claudeAiOauth", {}).get("accessToken")
                if token:
                    return token
            except Exception:
                pass

        cred_file = os.path.expanduser("~/.claude/.credentials.json")
        if os.path.exists(cred_file):
            try:
                with open(cred_file) as f:
                    data = json.load(f)
                token = data.get("claudeAiOauth", {}).get("accessToken")
                if token:
                    return token
            except Exception as e:
                logger.error(f"Error reading {cred_file}: {e}")

        raise RuntimeError("No active Claude subscription credentials found in Keychain or ~/.claude/.credentials.json")

class CodexAuth:
    """Retrieves ChatGPT Codex OAuth tokens or API key from ~/.codex/auth.json."""

    @staticmethod
    def get_credentials() -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        auth_file = os.path.expanduser("~/.codex/auth.json")
        if not os.path.exists(auth_file):
            raise RuntimeError(f"Codex credentials not found at {auth_file}")

        with open(auth_file) as f:
            data = json.load(f)

        auth_mode = data.get("auth_mode", "chatgpt")
        api_key = data.get("OPENAI_API_KEY")
        tokens = data.get("tokens", {})
        access_token = tokens.get("access_token")
        account_id = tokens.get("account_id")

        return auth_mode, access_token, account_id, api_key


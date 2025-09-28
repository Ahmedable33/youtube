from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


DEFAULT_CLIENT_SECRETS = "config/client_secret.json"
DEFAULT_TOKEN_FILE = "config/token.json"


def get_credentials(
    scopes: Iterable[str],
    client_secrets_path: str | Path = DEFAULT_CLIENT_SECRETS,
    token_path: str | Path = DEFAULT_TOKEN_FILE,
    *,
    port: int = 0,
    headless: bool = False,
) -> Credentials:
    """
    Obtenir des identifiants OAuth2.0. Réutilise `token.json` si présent, sinon lance le flux OAuth local.

    Args:
        scopes: Liste des scopes requis.
        client_secrets_path: Chemin vers client_secret.json.
        token_path: Chemin vers le fichier de token (sera créé/écrasé si nécessaire).
        port: Port du serveur local pour le flux OAuth (0 = port aléatoire).
        headless: Si True, utilise un flux console au lieu d'ouvrir le navigateur.

    Returns:
        Credentials: Identifiants valides pour appeler l'API YouTube.
    """
    client_secrets_path = Path(client_secrets_path)
    token_path = Path(token_path)
    token_path.parent.mkdir(parents=True, exist_ok=True)

    creds: Optional[Credentials] = None

    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)  # type: ignore[arg-type]
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            _save_token(token_path, creds)
            return creds
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if not client_secrets_path.exists():
            # Fallback: chercher à la racine du projet
            root_candidate = Path("client_secret.json")
            if root_candidate.exists():
                client_secrets_path = root_candidate
            else:
                raise FileNotFoundError(
                    "Fichier d'identifiants introuvable. Cherché: "
                    f"{Path(DEFAULT_CLIENT_SECRETS).resolve()} et {root_candidate.resolve()}"
                )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secrets_path), scopes
        )
        if headless:
            creds = flow.run_console()
        else:
            creds = flow.run_local_server(port=port)
        _save_token(token_path, creds)

    return creds


def _save_token(path: Path, creds: Credentials) -> None:
    data = creds.to_json()
    path.write_text(data, encoding="utf-8")

"""Baixa os modelos preditivos do GitHub Actions Artifact para a pasta local.

Usado no startup do Render (free tier) para nao versionar os .pkl no repo.
Requer as env vars:
  MODELS_ARTIFACT_REPO  ex.: julio-cesar/AutoAssist
  MODELS_ARTIFACT_NAME  ex.: predictive-models (padrao)
  GITHUB_TOKEN          opcional; se ausente, tenta artifact publico via API.
"""
import os
import sys
import json
import shutil
import zipfile
import urllib.request
from pathlib import Path

REPO = os.getenv("MODELS_ARTIFACT_REPO", "")
ARTIFACT_NAME = os.getenv("MODELS_ARTIFACT_NAME", "predictive-models")
TARGET = Path(os.getenv("PREDICTIVE_MODEL_DIR", ""))
if not TARGET or str(TARGET) == ".":
    TARGET = Path(__file__).resolve().parent.parent / "models" / "predictive"
TARGET.mkdir(parents=True, exist_ok=True)

API = f"https://api.github.com/repos/{REPO}/actions/artifacts?per_page=100"


def _get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main() -> int:
    if not REPO:
        print("[download_models] MODELS_ARTIFACT_REPO nao definido; pulando.")
        return 0

    token = os.getenv("GH_TOKEN") or os.getenv("MODELS_GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        data = _get(API, headers)
    except Exception as e:
        print(f"[download_models] falha ao listar artifacts: {e}")
        return 1

    artifact = next((a for a in data.get("artifacts", []) if a["name"] == ARTIFACT_NAME), None)
    if not artifact:
        print(f"[download_models] artifact '{ARTIFACT_NAME}' nao encontrado.")
        return 1
    if artifact.get("expired"):
        print(f"[download_models] artifact '{ARTIFACT_NAME}' expirado.")
        return 1

    print(f"[download_models] baixando artifact id={artifact['id']}...")
    try:
        req = urllib.request.Request(artifact["archive_download_url"], headers=headers)
        zip_path = TARGET / "_models_artifact.zip"
        with urllib.request.urlopen(req, timeout=60) as r, open(zip_path, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(zip_path) as z:
            for member in z.namelist():
                # O artifact preserva o path completo (backend/models/predictive/...).
                # Extrai so o nome do arquivo, achatando a estrutura.
                filename = member.split("/")[-1]
                if not filename:
                    continue
                with z.open(member) as src, open(TARGET / filename, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        zip_path.unlink()
    except Exception as e:
        print(f"[download_models] falha no download: {e}")
        return 1

    print(f"[download_models] modelos em {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

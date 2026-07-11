import os
import sys
import json
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
KEY_FILE = BASE_DIR / ".env.key"
ENCRYPTED_ENV_FILE = BASE_DIR / ".env.encrypted"

def _derive_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))

def generate_key(master_password: str) -> bytes:
    salt = os.urandom(16)
    key = _derive_key(master_password, salt)
    key_file_data = base64.urlsafe_b64encode(salt + key).decode()
    KEY_FILE.write_text(key_file_data)
    return key

def load_key(master_password: str | None = None) -> bytes | None:
    if not KEY_FILE.exists():
        return None
    raw = KEY_FILE.read_text().strip()
    try:
        decoded = base64.urlsafe_b64decode(raw)
        salt = decoded[:16]
        stored_key = decoded[16:]
        if master_password:
            derived = _derive_key(master_password, salt)
            if derived != stored_key:
                raise ValueError("Master password incorreta")
        return stored_key
    except Exception:
        raise ValueError("Falha ao carregar chave de criptografia")

def encrypt_env(master_password: str):
    if not ENV_FILE.exists():
        print("Arquivo .env nao encontrado.")
        return
    key = load_key(master_password) or generate_key(master_password)
    fernet = Fernet(key)
    content = ENV_FILE.read_bytes()
    encrypted = fernet.encrypt(content)
    ENCRYPTED_ENV_FILE.write_bytes(encrypted)
    print(f".env criptografado -> {ENCRYPTED_ENV_FILE}")

def decrypt_env(master_password: str) -> str | None:
    if not ENCRYPTED_ENV_FILE.exists():
        return None
    key = load_key(master_password)
    if not key:
        raise ValueError("Chave de criptografia nao encontrada. Execute generate_key primeiro.")
    fernet = Fernet(key)
    decrypted = fernet.decrypt(ENCRYPTED_ENV_FILE.read_bytes())
    return decrypted.decode()

def load_env_decrypted():
    """Carrega variaveis do .env criptografado, se existir, ou do .env normal."""
    if ENCRYPTED_ENV_FILE.exists():
        master_pw = os.getenv("ENV_MASTER_PASSWORD")
        if not master_pw:
            print("AVISO: ENV_MASTER_PASSWORD nao definida, tentando .env normal")
            if ENV_FILE.exists():
                return str(ENV_FILE)
            return None
        content = decrypt_env(master_pw)
        if content:
            from dotenv import load_dotenv
            import io
            load_dotenv(stream=io.StringIO(content))
            print("Variaveis carregadas do .env criptografado")
            return None
    return str(ENV_FILE) if ENV_FILE.exists() else None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python utils/secrets_encrypt.py <encrypt|decrypt> [master_password]")
        sys.exit(1)
    action = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else os.getenv("ENV_MASTER_PASSWORD")
    if not password:
        print("Defina ENV_MASTER_PASSWORD ou passe como argumento")
        sys.exit(1)
    if action == "encrypt":
        encrypt_env(password)
    elif action == "decrypt":
        print(decrypt_env(password))
    else:
        print("Acao invalida. Use encrypt ou decrypt.")

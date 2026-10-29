"""Create local credentials once. Never overwrite an existing .env."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / '.env'
    if target.exists():
        print('.env already exists; left unchanged.')
        return
    owner, reader = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    target.write_text(
        f'POSTGRES_PASSWORD={owner}\nANALYST_DB_PASSWORD={reader}\n'
        f'DATABASE_URL=postgresql+psycopg://analyst_reader:{reader}@127.0.0.1:55432/enterprise_analytics\n'
        'LLM_API_KEY=\nLLM_BASE_URL=https://api.openai.com/v1\nLLM_MODEL=\n'
        'SQL_TIMEOUT_MS=5000\nSQL_MAX_ROWS=500\n', encoding='utf-8')
    print('Created .env with local database credentials. Configure LLM_API_KEY and LLM_MODEL for AI queries.')


if __name__ == '__main__':
    main()

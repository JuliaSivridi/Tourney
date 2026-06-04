from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
WEBAPP_URL: str = os.getenv("WEBAPP_URL", "http://localhost")
WEBAPP_PORT: int = int(os.getenv("WEBAPP_PORT", "8003"))

# DB credentials — kept separate so special chars in password don't break URL parsing
POSTGRES_USER: str = os.getenv("POSTGRES_USER", "tourney")
POSTGRES_PASSWORD: str = os.environ["POSTGRES_PASSWORD"]
POSTGRES_DB: str = os.getenv("POSTGRES_DB", "tourney")
POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "db")
POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))

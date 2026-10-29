import os

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "Configure SUPABASE_URL e SUPABASE_SECRET_KEY no arquivo .env"
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)
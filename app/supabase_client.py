import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

raw_supabase_url = (os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_URL = raw_supabase_url.split("/rest/v1")[0].rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("Server running and connected to Supabase")

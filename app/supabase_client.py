
import os

from dotenv import load_dotenv
from supabase import create_client, Client

# Membaca konfigurasi dari file .env
load_dotenv()

# Mengambil credentials dari environment
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Memastikan konfigurasi tersedia
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL atau SUPABASE_KEY belum diatur di .env")

# Membuat koneksi client Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("Supabase client initialized successfully!")

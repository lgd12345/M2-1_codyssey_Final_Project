"""Explicitly import model names from the original CSV into the application DB."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psycopg
from dotenv import load_dotenv
from app.service_requests.model_catalog import import_models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--allow-current-db', action='store_true', required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        models = import_models(connection, args.csv)
    print(f'Imported {len(models)} distinct CSV models (idempotent).')


if __name__ == '__main__':
    main()

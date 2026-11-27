import asyncio
import json
import os
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from playwright.async_api import async_playwright

# ==========================================
# CONFIGURATION
# ==========================================

BET261_URL = os.getenv(
    "BET261_URL",
    "https://bet261.mg/sports/102"
)

COLLECTION_MINUTES = int(os.getenv("COLLECTION_MINUTES", "30"))
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "15"))

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "races.json"

DATA_DIR.mkdir(exist_ok=True)


# ==========================================
# DATABASE
# ==========================================

def load_database():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "project": "BET261 PUBLIC COLLECTOR",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "observations": []
    }


def save_database(database):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(database, f, indent=2, ensure_ascii=False)


# ==========================================
# TEXT PROCESSING
# ==========================================

def clean_text(text):
    lines = []

    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()

        if line and len(line) > 1:
            lines.append(line)

    return lines


def identify_numbers(text):
    return re.findall(r"\b\d+(?:[.,]\d+)?\b", text)


def make_hash(url, text):
    raw = url + "|" + text
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ==========================================
# COLLECTOR
# ==========================================

async def collect():

    database = load_database()

    seen_hashes = {
        item["hash"]
        for item in database["observations"]
        if "hash" in item
    }

    end_time = (
        asyncio.get_running_loop().time()
        + COLLECTION_MINUTES * 60
    )

    async with async_playwright() as playwright:

        browser = await playwright.chromium.launch(
            headless=True
        )

        page = await browser.new_page(
            viewport={"width": 1440, "height": 1000},
            locale="fr-FR"
        )

        print("Ouverture de Bet261...")

        try:
            await page.goto(
                BET261_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )
        except Exception as error:
            print("Erreur ouverture:", error)

        await page.wait_for_timeout(10000)

        while asyncio.get_running_loop().time() < end_time:

            try:
                # Lire uniquement le texte visible de la page
                text = await page.locator("body").inner_text(
                    timeout=15000
                )

                lines = clean_text(text)
                full_text = "\n".join(lines)

                current_url = page.url
                observation_hash = make_hash(
                    current_url,
                    full_text
                )

                if full_text and observation_hash not in seen_hashes:

                    observation = {
                        "timestamp": datetime.now(
                            timezone.utc
                        ).isoformat(),
                        "url": current_url,
                        "hash": observation_hash,
                        "text": full_text,
                        "numbers": identify_numbers(full_text)
                    }

                    database["observations"].append(
                        observation
                    )

                    seen_hashes.add(observation_hash)

                    save_database(database)

                    print(
                        "Nouvelle observation enregistrée:",
                        observation["timestamp"]
                    )

                else:
                    print("Aucun nouveau texte.")

            except Exception as error:
                print("Erreur collecte:", error)

            await asyncio.sleep(INTERVAL_SECONDS)

        await browser.close()

    save_database(database)

    print("Collecte terminée.")
    print(
        "Nombre total d'observations:",
        len(database["observations"])
    )


# ==========================================
# START
# ==========================================

if __name__ == "__main__":
    asyncio.run(collect())
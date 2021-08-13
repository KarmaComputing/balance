from fastapi import FastAPI
import requests
from dotenv import load_dotenv
import logging
import os
from babel.numbers import format_currency

log = logging.getLogger()

load_dotenv(verbose=True)

log.setLevel(os.getenv("PYTHON_LOGLEVEL", logging.DEBUG))

PERSONAL_ACCESS_TOKEN = os.getenv("PERSONAL_ACCESS_TOKEN")
BANK_ACCOUNT_ID = os.getenv("BANK_ACCOUNT_ID")

headers = {
    "Authorization": PERSONAL_ACCESS_TOKEN,
    "accept": "application/json",
}


app = FastAPI()


@app.get("/")
def balance():
    host = f"https://api.starlingbank.com/api/v2/accounts/{BANK_ACCOUNT_ID}/balance"  # noqa
    req = requests.get(host, headers=headers)
    resp = req.json()
    balance = resp["clearedBalance"]["minorUnits"]
    balance_human_readable = format_currency(
        balance / 100, "GBP", locale="en_GB"
    )  # noqa
    resp = {
        "balance": balance,
        "balance-human-readable": f"{balance_human_readable}",
    }  # noqa
    return resp

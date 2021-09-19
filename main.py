from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from dotenv import load_dotenv
import logging
import os
from babel.numbers import format_currency
import io
import csv

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/statement/available-periods")
def get_available_periods():
    host = f"https://api.starlingbank.com/api/v2/accounts/{BANK_ACCOUNT_ID}/statement/available-periods"  # noqa
    req = requests.get(host, headers=headers)
    resp = req.json()
    return resp


@app.get("/statement/downloadForDateRange")
def get_statement_range_CSV(DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD: str = None):
    host = f"https://api.starlingbank.com/api/v2/accounts/{BANK_ACCOUNT_ID}/statement/downloadForDateRange"  # noqa
    host += "?start=2021-08-17"
    host += "&end=2021-09-17"
    headers["accept"] = "text/csv"
    req = requests.get(host, headers=headers)
    resp = req.text
    if (
        DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD is not None
        and DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD
        == os.getenv("DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD")
    ):
        return resp
    else:  # Hide transaction details
        fp = io.StringIO(resp)
        csvreader = csv.reader(fp, delimiter=",")
        rows = []
        for row in csvreader:
            row[1] = "#"
            row[2] = "#"
            rows.append(row)
        return rows


@app.get("/cashflow-this-month")
def calculate_cashflow():
    statementCSV = get_statement_range_CSV()
    credits = []
    debits = []
    for row in statementCSV[1:-1]:  # Skip header
        amount = float(row[4])
        if amount < 0:
            debits.append(amount)
        else:
            credits.append(amount)

    total_credits = round(sum(credits), 2)
    total_credits_human_readable = format_currency(total_credits, "GBP", locale="en_GB")
    total_debits = round(sum(debits), 2)
    total_debits_human_readable = format_currency(total_debits, "GBP", locale="en_GB")
    cashflow = round(total_credits + total_debits, 2)
    cashflow_human_readable = format_currency(cashflow, "GBP", locale="en_GB")
    return {
        "cashflow": cashflow,
        "cashflow-human-readable": cashflow_human_readable,
        "total-credits": total_credits,
        "total-credits-human-readable": total_credits_human_readable,
        "total-debits": total_debits,
        "total-debits-human-readable": total_debits_human_readable,
        "credits": credits,
        "debits": debits,
        "statement": statementCSV,
    }

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from dotenv import load_dotenv
import logging
import os
from babel.numbers import format_currency
import io
import csv
from datetime import date, timedelta
import calendar

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
def get_statement_range_CSV(
    startDate: str = "yyyy-mm-dd",
    endDate: str = "yyyy-mm-dd",
    DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD: str = None,
):
    host = f"https://api.starlingbank.com/api/v2/accounts/{BANK_ACCOUNT_ID}/statement/downloadForDateRange"  # noqa
    breakpoint()
    host += f"?start={startDate}"
    host += f"&end={endDate}"

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
    today = date.today()
    startDate = today.strftime("%Y-%m-01")  # Always first day of current month
    last_day = calendar.monthrange(today.year, int(today.month))[1]
    endDate = today.strftime(f"%Y-%m-{last_day}")

    statementCSV = get_statement_range_CSV(
        startDate=startDate, endDate=endDate
    )  # noqa: E501
    credits = []
    debits = []
    for row in statementCSV[1:-1]:  # Skip header
        amount = float(row[4])
        if amount < 0:
            debits.append(amount)
        else:
            credits.append(amount)

    total_credits = round(sum(credits), 2)
    total_credits_human_readable = format_currency(
        total_credits, "GBP", locale="en_GB"
    )  # noqa: E501
    total_debits = round(sum(debits), 2)
    total_debits_human_readable = format_currency(
        total_debits, "GBP", locale="en_GB"
    )  # noqa: E501
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


@app.get("/cashflow-last-month")
def calculate_cashflow_last_month():

    endDate = date.today().replace(day=1) - timedelta(days=1)
    startDate = (date.today().replace(day=1) - timedelta(days=endDate.day)).strftime(
        "%Y-%m-01"
    )
    endDate = endDate.strftime("%Y-%m-%d")
    breakpoint()

    statementCSV = get_statement_range_CSV(
        startDate=startDate, endDate=endDate
    )  # noqa: E501
    credits = []
    debits = []
    for row in statementCSV[1:-1]:  # Skip header
        amount = float(row[4])
        if amount < 0:
            debits.append(amount)
        else:
            credits.append(amount)

    total_credits = round(sum(credits), 2)
    total_credits_human_readable = format_currency(
        total_credits, "GBP", locale="en_GB"
    )  # noqa: E501
    total_debits = round(sum(debits), 2)
    total_debits_human_readable = format_currency(
        total_debits, "GBP", locale="en_GB"
    )  # noqa: E501
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

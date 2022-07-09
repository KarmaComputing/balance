from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from dotenv import load_dotenv
import logging
import os
from babel.numbers import format_currency
import io
import csv
from datetime import date, timedelta, datetime
import calendar
from typing import Optional

log = logging.getLogger()

load_dotenv(verbose=True)

log.setLevel(os.getenv("PYTHON_LOGLEVEL", logging.DEBUG))

PERSONAL_ACCESS_TOKEN = os.getenv("PERSONAL_ACCESS_TOKEN")
BANK_ACCOUNT_ID = os.getenv("BANK_ACCOUNT_ID")

headers = {
    "Authorization": PERSONAL_ACCESS_TOKEN,
    "accept": "application/json",
}


title = "Karma Computing Accounts"
description = """
View balance, and cashflow. <small>[Code](https://github.com/KarmaComputing/balance)</small> 🚀

# See also

## Recurring Revenue

- [Monthly Recurring Revenue](https://reccuring-revenue.pcpink.co.uk/docs) ([Code](https://github.com/KarmaComputing/reccuring-revenue/))

## Time Invested API

- [Ad-Hoc support](https://time.karmacomputing.co.uk/) ([Code](https://github.com/KarmaComputing/time-api))

"""

app = FastAPI(title=title, description=description)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def balance():
    host = f"https://api.starlingbank.com/api/v2/accounts/{BANK_ACCOUNT_ID}/balance"  # noqa E501
    headers["accept"] = "application/json"
    req = requests.get(host, headers=headers)
    if req.status_code != 200:
        print(f"Error getting balance:\nStatus:{req.status_code}\n{req.text}")
        return "Error getting balance, check the logs"

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
    host += f"?start={startDate}"
    host += f"&end={endDate}"

    headers["accept"] = "text/csv"
    req = requests.get(host, headers=headers)
    resp = req.text
    fp = io.StringIO(resp)
    csvreader = csv.reader(fp, delimiter=",")
    rows = []
    for row in csvreader:
        if (
            DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD is not None
            and DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD
            == os.getenv("DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD")
        ):
            pass
        else:
            row[1] = "#"
            row[2] = "#"
        rows.append(row)
    return rows


def calculateCashflow(statementCSV):
    credits = []
    debits = []
    try:
        for row in statementCSV[1:-1]:  # Skip header
            amount = float(row[4])
            if amount < 0:
                debits.append(amount)
            else:
                credits.append(amount)
    except IndexError as e:
        print(f"{e}")
        print("error")

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
        "statement": statementCSVtoJson(statementCSV),
    }


def statementCSVtoJson(statementCSV):
    # ['Date', 'Counter Party', 'Reference', 'Type', 'Amount (GBP)', 'Balance (GBP)', 'Spending Category', 'Notes']
    statementItems = []
    for statementItem in statementCSV:
        statementItems.append(
            {
                "date": statementItem[0],
                "counterparty": statementItem[1],
                "reference": statementItem[2],
                "type": statementItem[3],
                "amount-gbp": statementItem[4],
                "balance-gbp": statementItem[5],
                "spending-category": statementItem[6],
                "notes": statementItem[7],
            }
        )
    return statementItems


@app.get("/cashflow-this-month")
def calculate_cashflow():
    today = date.today()
    startDate = today.strftime("%Y-%m-01")  # Always first day of current month
    last_day = calendar.monthrange(today.year, int(today.month))[1]
    endDate = today.strftime(f"%Y-%m-{last_day}")

    statementCSV = get_statement_range_CSV(
        startDate=startDate, endDate=endDate
    )  # noqa: E501

    return calculateCashflow(statementCSV)


@app.get("/cashflow-last-month")
def calculate_cashflow_last_month():

    endDate = date.today().replace(day=1) - timedelta(days=1)
    startDate = (
        date.today().replace(day=1) - timedelta(days=endDate.day)
    ).strftime(  # noqa: E501
        "%Y-%m-01"
    )
    endDate = endDate.strftime("%Y-%m-%d")

    statementCSV = get_statement_range_CSV(
        startDate=startDate, endDate=endDate
    )  # noqa: E501

    return calculateCashflow(statementCSV)


@app.get("/cashflow-by-month")
def calculate_cashflow_by_month(
    startDate: str = "yyyy-mm-dd", endDate: Optional[str] = None
):
    if endDate is None:
        # If endDate is none, automatically work out
        # the last day of the month for the chosen startDate
        start = datetime.strptime(startDate, "%Y-%m-%d")
        last_day = calendar.monthrange(start.year, int(start.month))[1]
        endDate = start.strftime(f"%Y-%m-{last_day}")

    statementCSV = get_statement_range_CSV(
        startDate=startDate, endDate=endDate
    )  # noqa: E501

    return calculateCashflow(statementCSV)


@app.get("/cashflow-last-n-months")
def cashflow_last_n_months(
    number_of_months: int = 3,
    DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD: str = None,  # noqa: E501
    include_this_month: bool = False,
):
    """Display cashflow for the last n months"""
    cashflows = []

    # Get last month from today
    endDate = date.today().replace(day=1)
    if include_this_month is False:  # By default, we *don't* include current month.
        endDate = date.today().replace(day=1) - timedelta(days=1)

    startDate = date.today().replace(day=1) - timedelta(days=endDate.day)
    i = 0
    while i < number_of_months:
        statementCSV = get_statement_range_CSV(
            startDate=startDate.strftime("%Y-%m-01"),
            endDate=endDate.strftime("%Y-%m-%d"),
            DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD=DISPLAY_FULL_STATEMENT_DETAIL_PASSWORD,  # noqa: E501
        )  # noqa: E501
        cashflows.append(
            {startDate.strftime("%b-%Y"): calculateCashflow(statementCSV)}
        )  # noqa: E501

        # Got back another month
        endDate = endDate.replace(day=1) - timedelta(days=1)
        startDate = endDate.replace(day=1)
        i += 1

    return cashflows

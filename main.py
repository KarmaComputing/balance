from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
from SimpleRedis import SimpleRedis


log = logging.getLogger()
handler = logging.StreamHandler()  # sys.stderr will be used by default

load_dotenv(verbose=True)

PYTHON_LOG_LEVEL = os.getenv("PYTHON_LOG_LEVEL", logging.DEBUG)
log.setLevel(PYTHON_LOG_LEVEL)

handler.setLevel(PYTHON_LOG_LEVEL)
handler.setFormatter(
    logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)-8s %(message)s %(funcName)s %(pathname)s:%(lineno)d"  # noqa: E501
    )
)

log.addHandler(handler)

# Establish Simple shared memory for rate limmit back-off
# tracking
# Note we use a single entry seperated by a comma (,) e.g:
# <retry-until-after-timestamp>,<timestamp-of-last-lookup>,<last-known-balance>
# e.g  1739108227,1739108516,44443
# means:
# retry after timestamp,last lookup timestamp of 1739108516, balance of 44443 (£444.43)  # noqa: E501
simpleRedis = SimpleRedis()
simpleRedis.free()


PERSONAL_ACCESS_TOKEN = os.getenv("PERSONAL_ACCESS_TOKEN")
BANK_ACCOUNT_ID = os.getenv("BANK_ACCOUNT_ID")
MIN_SECS_BETWEEN_API_CALL = os.getenv("MIN_SECS_BETWEEN_API_CALL", 3)
BALANCE_CACHE_FALLBACK_FILENAME = os.getenv(
    "BALANCE_CACHE_FALLBACK_FILENAME", "balance-file-cache"
)

headers = {
    "Authorization": PERSONAL_ACCESS_TOKEN,
    "accept": "application/json",
}


title = "Karma Computing Accounts"
description = """
View balance, and cashflow. <small>[Code](https://github.com/KarmaComputing/balance)</small> 🚀  # noqa: E501

# See also

## Recurring Revenue

- [Monthly Recurring Revenue](https://reccuring-revenue.pcpink.co.uk/docs) ([Code](https://github.com/KarmaComputing/reccuring-revenue/))

## Time Invested API

- [Ad-Hoc support](https://time.karmacomputing.co.uk/) ([Code](https://github.com/KarmaComputing/time-api))

## Balance Sheet

[Balance sheet](http://balancesheet.karmacomputing.co.uk/

"""

app = FastAPI(title=title, description=description)
app.is_rate_limited = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def build_balance_response(balance: int):
    balance_human_readable = format_currency(
        balance / 100, "GBP", locale="en_GB"
    )  # noqa
    resp = {
        "balance": balance,
        "balance-human-readable": f"{balance_human_readable}",
    }  # noqa
    return resp


def bootstrap():
    """pre-reqs"""
    get_last_known_balance()


def read_cache():
    try:
        retry_after_tstamp, last_lookup_tstamp, last_known_balance = (
            bytes(simpleRedis.shm.buf[:])
            .decode("utf-8")
            .rstrip("\x00")
            .split(",")  # noqa: E501
        )
        return retry_after_tstamp, last_lookup_tstamp, last_known_balance
    except ValueError as e:
        msg = (
            f"{e}. shared memory cache appears empty or corrupt "
            "re-populating from BALANCE_CACHE_FALLBACK_FILENAME "
            "using datetime.now() with -1 for balance as final fallback"
        )
        log.debug(msg)

        msg = f"{e} ValueError There is no cached balance to show"
        log.info(msg)
        log.info("Falling back to BALANCE_CACHE_FALLBACK_FILENAME lookup")
        with open(BALANCE_CACHE_FALLBACK_FILENAME, "r") as fp:
            (
                retry_after_tstamp,
                last_lookup_tstamp,
                last_known_balance,
            ) = fp.read().split(  # noqa: E501
                ","
            )
            last_known_balance = int(last_known_balance)
            log.debug(
                f"Returning: {retry_after_tstamp},"
                f"{last_lookup_tstamp},{last_known_balance}"
            )
            return retry_after_tstamp, last_lookup_tstamp, last_known_balance
    except Exception as e:
        msg = (
            f"{e}. Unable to get_last_known_balance from "
            "shared memory or BALANCE_CACHE_FALLBACK_FILENAME fallback"
        )
        log.error(msg)
        return -1

    return retry_after_tstamp, last_lookup_tstamp, last_known_balance


def get_last_known_balance() -> int:
    """ "
    # First lookup shared memory cache
    # Then BALANCE_CACHE_FALLBACK_FILENAME
    """
    try:
        retry_after_tstamp, last_lookup_tstamp, last_known_balance = (
            read_cache()
        )  # noqa: E501
        last_known_balance = int(last_known_balance)
        return last_known_balance
    except ValueError as e:
        log.info(f"{e} Falling back to BALANCE_CACHE_FALLBACK_FILENAME lookup")
        with open(BALANCE_CACHE_FALLBACK_FILENAME, "r") as fp:
            (
                retry_after_tstamp,
                last_lookup_tstamp,
                last_known_balance,
            ) = fp.read().split(  # noqa: E501
                ","
            )
            last_known_balance = int(last_known_balance)
            return last_known_balance
    except Exception as e:
        log.debug(
            f"{e} Could not get balance from "
            " BALANCE_CACHE_FALLBACK_FILENAME Final bootstrap fallback.\n"
            "Populating dummy BALANCE_CACHE_FALLBACK_FILENAME and "
            "populating shared memory with datetime.now() values and "
            "-1 for balance"
        )

        log.debug(
            "Writing BALANCE_CACHE_FALLBACK_FILENAME "
            f"{BALANCE_CACHE_FALLBACK_FILENAME}"
        )
        nowTs = int(datetime.now().timestamp())
        balance = -1
        value = f"{nowTs},{nowTs},{balance}".encode("utf-8")
        with open(BALANCE_CACHE_FALLBACK_FILENAME, "w") as fp:
            fp.write(f"{nowTs},{nowTs},-1")

        log.debug(f"Populating shared memory with bootstrapped value: {value}")
        simpleRedis.put(value)


bootstrap()


def get_cached_balance_resp() -> dict:
    retry_after_tstamp, last_lookup_tstamp, last_known_balance = (
        read_cache()
    )  # noqa: E501

    respDict = build_balance_response(int(last_known_balance))
    return respDict


@app.get("/")
def balance(request: Request):
    try:
        log.info(
            "Checking time between last lookup is "
            "less than MIN_SECS_BETWEEN_API_CALL"
        )

        retry_after_tstamp, last_lookup_tstamp, last_known_balance = (
            read_cache()
        )  # noqa: E501

        now = datetime.now()
        last_lookup_tstamp = datetime.fromtimestamp(int(last_lookup_tstamp))
        time_diff_in_secs = (now - last_lookup_tstamp).total_seconds()
        if time_diff_in_secs < MIN_SECS_BETWEEN_API_CALL:
            remaining_wait_time = MIN_SECS_BETWEEN_API_CALL - time_diff_in_secs
            msg = {
                "warning": f"{remaining_wait_time} secs remain until "
                "MIN_SECS_BETWEEN_API_CALL exceeded. "
                "Consider calling /balance-cached endpoint instead"
            }
            log.info("Including cached balance in response")
            cachedBalance = get_cached_balance_resp()
            msg = msg | cachedBalance
            log.error(msg)
            # Include cached balance in response
            resp = build_balance_response(int(last_known_balance))
            resp = msg | resp

            return JSONResponse(content=msg, status_code=503)

    except ValueError as e:
        last_known_balance = get_last_known_balance()
        log.info(
            f"{e}. Could not determin last api lookup time "
            "continuing with live api call"
        )
        if "bypass_cache" not in request.query_params:
            log.info("Falling back to file cache lookup")
            with open(BALANCE_CACHE_FALLBACK_FILENAME, "r") as fp:
                (
                    retry_after_tstamp,
                    last_lookup_tstamp,
                    last_known_balance,
                ) = fp.read().split(  # noqa: E501
                    ","
                )
                last_lookup_date = datetime.fromtimestamp(
                    int(last_lookup_tstamp)
                )  # noqa: E501
                msg = {
                    "warning": "This is a fallback response "
                    "from BALANCE_CACHE_FALLBACK_FILENAME "
                    "because shared memory lookup was empty. "
                    f"The file last_lookup_date is: {last_lookup_date}"
                }
                resp = build_balance_response(int(last_known_balance)) | msg
                return JSONResponse(content=resp, status_code=503)

    host = f"https://api.starlingbank.com/api/v2/accounts/{BANK_ACCOUNT_ID}/balance"  # noqa E501
    headers["accept"] = "application/json"
    req = requests.get(host, headers=headers)
    lookupTimestamp = int(datetime.now().timestamp())
    log.info(f"req.status_code is {req.status_code}")
    if req.status_code == 200:
        resp = req.json()
        balance = resp["clearedBalance"]["minorUnits"]
        log.debug("Updating BALANCE_CACHE_FALLBACK_FILENAME last-resort cache")
        with open(BALANCE_CACHE_FALLBACK_FILENAME, "w") as fp:
            nowTs = int(datetime.now().timestamp())
            fp.write(f"{nowTs},{nowTs},{balance}")

        # Even though we're not rate-limited at this point,
        # we place a dummy retry-after timestamp equal to
        # lookupTimestamp so that there's a non empty value there.
        value = f"{lookupTimestamp},{lookupTimestamp},{balance}".encode(
            "utf-8"
        )  # noqa: E501
        log.info(
            "Storing sucessful balance call in shared memory "
            "so that we may reference this stale value if we get rate limited:"
            f"Value: {value}"
        )
        simpleRedis.put(value)
    if req.status_code != 200:
        log.error(f"Get balance error: Status:{req.status_code}\n{req.text}")
        msg = {"warning": "Error getting balance, check the logs"}
        try:
            if "Retry-After" in req.headers:
                retry_after_seconds = int(req.headers["Retry-After"])

                # This is likely the first time we've been rate limited
                # asked to wait.

                # Calculate time in future when should be OK
                # to retry, and store that in shared memory
                # so that when we read it, we can determine if it's
                # OK to retry.
                now = datetime.now()
                retryDeltaSecs = timedelta(seconds=retry_after_seconds)
                nextRetryAllowedTime = now + retryDeltaSecs
                nextRetryAllowedTimestamp = str(
                    int(nextRetryAllowedTime.timestamp())
                )  # noqa: E501
                value = f"{nextRetryAllowedTimestamp},{lookupTimestamp},{last_known_balance}"  # noqa: E501
                simpleRedis.put(value.encode("utf-8"))

                # Check if we already have a backoff delay
                # Check if Retry-After has expired
                # by comparing now timestamp to
                # timestamp we stored at last entry
                now = int(datetime.now().timestamp())

                if now < int(retry_after_tstamp):
                    msg["warning"] += (
                        " Need to wait since Retry-After "
                        "has not elapsed yet "
                        f"{now} is not greater than "
                        f"{retry_after_tstamp}"
                    )
                    log.info(msg)
            msg = get_cached_balance_resp() | msg
            log.debug("returning response with cached balance:\n" f"{msg}")
            return JSONResponse(content=msg, status_code=503)
        except Exception as e:
            log.error(
                f"Could not parse as json response:\n{e} "
                f"The req status_code was {req.status_code} {req.reason}\n"
                f"The response text was: {req.text}\n"
                f"The response headers were: {req.headers}\n"
            )
        raise HTTPException(status_code=400, detail=msg)

    resp = build_balance_response(balance)

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
    # ['Date', 'Counter Party', 'Reference', 'Type', 'Amount (GBP)', 'Balance (GBP)', 'Spending Category', 'Notes']  # noqa: E501
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
    endDate = date.today()
    if (
        include_this_month is False
    ):  # By default, we *don't* include current month.  # noqa: E501
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

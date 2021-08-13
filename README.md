# Quickly see balance

## Setup & run locally
```
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
cp .env.example .env # and set to sandbox environment.
```

### Run
```
uvicorn main:app --reload
```
Visit http://127.0.0.1:8000




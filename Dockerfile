FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway (and most PaaS hosts) inject PORT at runtime -- shell form so it
# actually expands. DB_PATH should point at a mounted persistent volume
# (see README's "Hosting" section) so the SQLite file survives redeploys.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

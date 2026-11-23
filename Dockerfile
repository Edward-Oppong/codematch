FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CODEMATCH_ALLOWED_HOSTS=* \
    PORT=5000

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

EXPOSE 5000

CMD ["sh", "-c", "gunicorn run:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120"]

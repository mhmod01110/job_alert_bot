FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app --home /home/app app

COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app job_alert_bot ./job_alert_bot
COPY --chown=app:app profile.yaml ./profile.yaml

RUN mkdir -p /app/data \
    && touch /app/data/.keep \
    && chown -R app:app /app /home/app

USER app

CMD ["python", "-m", "job_alert_bot"]

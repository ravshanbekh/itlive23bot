FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system --gid 10001 itlive \
    && useradd --system --uid 10001 --gid itlive --create-home itlive

COPY --chown=10001:10001 itlive ./itlive
USER 10001:10001

EXPOSE 8080
CMD ["python", "-m", "itlive"]

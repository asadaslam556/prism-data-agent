FROM python:3.12-slim

WORKDIR /srv/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY pyproject.toml .

# don't run as root inside the container
RUN useradd --create-home appuser && chown -R appuser:appuser /srv/backend
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
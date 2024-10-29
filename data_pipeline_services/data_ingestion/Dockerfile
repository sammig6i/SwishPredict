FROM python:3.10-slim

WORKDIR /app/data_pipeline_services

COPY data_ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY . .

ENV PYTHONPATH=/app

CMD ["python", "data_ingestion/main.py"]
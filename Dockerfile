FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY . /app
ENV PYTHONPATH=/app/backend PYTHONUNBUFFERED=1
EXPOSE 8000 8501
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# The repo is mounted at /app by docker-compose; decisions/ and agent/ are imported from there.
ENV PYTHONPATH=/app:/app/decisions:/app/agent PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]

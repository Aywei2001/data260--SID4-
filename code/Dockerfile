FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt
COPY hw7_authentication.py homework_demo.py hw7_seed_users.py ./
CMD ["uvicorn", "hw7_authentication:app", "--host", "0.0.0.0", "--port", "8439"]

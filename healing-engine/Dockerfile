FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create runtime cache directory
RUN mkdir -p /app/data

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", "--reload"]

FROM python:3.11-slim

# Install Stockfish (Linux binary)
RUN apt-get update && apt-get install -y \
    stockfish \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set default Stockfish path for Docker
ENV STOCKFISH_PATH=/usr/bin/stockfish

# Run the worker
CMD ["python", "worker.py"]


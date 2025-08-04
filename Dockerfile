FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy app files
COPY logwatcher.py .
COPY requirements.txt .
COPY config.json .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the log watcher
CMD ["python", "logwatcher.py"]

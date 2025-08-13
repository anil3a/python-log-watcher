# LogWatcher

LogWatcher is a long-running Python service that monitors Apache/PHP log files in real-time and sends enriched error trace information to an `n8n` webhook endpoint. It includes Git blame, Apache vhost, and repo context.

## Features

* Tails log file with grouped multi-line PHP errors
* Git blame, Git remote, and Apache vhost metadata
* Sends to `n8n` via HTTP POST
* Uses in-memory TTL cache for performance
* Auto config reload without restart

## Installation (Host - Virtualenv Based)

```bash
git clone https://github.com/anil3a/python-log-watcher.git
cd logwatcher
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Edit `config.json`:

```json
{
  "enabled": true,
  "log_file": "/path/to/apache/error.log",
  "n8n_url": "https://n8n.yourdomainname.com.np/webhook/error"
}
```

## Running the Watcher (Host)

```bash
source venv/bin/activate
python logwatcher.py
```

## Docker-based Usage

### Dockerfile

```Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY logwatcher.py .
COPY requirements.txt .
COPY config.json .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "logwatcher.py"]
```

### Docker Compose (`docker-compose.yml`)

```yaml
services:
  logwatcher:
    build: .
    container_name: logwatcher
    volumes:
      - /var/log/apache2:/logs:ro
      - ./config.json:/app/config.json:ro
    restart: unless-stopped
```

### Update `config.json`

Make sure the log path inside the container is used:

```json
{
  "enabled": true,
  "log_file": "/logs/error.log",
  "n8n_url": "https://n8n.yourdomainname.com.np/webhook/error"
}
```

### Build and Run

```bash
docker-compose up --build -d
```

## Notes

* Requires `git` installed and accessible in `PATH`
* Works best on systems using Apache logs
* Tested on Linux (Debian/Ubuntu)


### Change log

* V1 is the first attempt to read error log
* V2 is the second attempt more enhancements
    * Uses cache tools to cache some variables for fast processing
    * Handles more error types
    * Parse more error types
    * More info in git details
    * Checks for local changs
    * An attempt to auto generate documentation using 

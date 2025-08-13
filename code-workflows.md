# LogWatcher Analysis

## 1. Possible Parameters and Outputs

### Parameters

The `LogWatcher` class is initialized with two parameters in its `__init__` method:

- `config_path` **(str, default:** `'config.json'`**)**

  - **Description**: Path to a JSON configuration file containing settings like the log file path, whether the service is enabled, and the n8n webhook URL.
  - **Possible Values**: Any valid file path to a JSON file (e.g., `'config.json'`, `'/etc/logwatcher/config.json'`, `'./configs/settings.json'`).
  - **Constraints**: The file must exist and contain valid JSON with expected keys (`log_file`, `enabled`, `n8n_url`). If the file is missing or invalid, the error is logged but not raised.

- `reload_interval` **(int, default:** `10`**)**

  - **Description**: Time interval (in seconds) after which the configuration file is reloaded to check for updates.
  - **Possible Values**: Any positive integer (e.g., `5`, `60`, `3600`). Smaller values increase reload frequency, while larger values reduce it.
  - **Constraints**: Must be a positive integer to avoid excessive reloads or division-by-zero errors in time calculations.

### Outputs

The `LogWatcher` class doesn’t return values directly but produces side effects, including:

1. **Console Output (Print Statements)**:

   - Logs configuration loading success or failure (e.g., `[CONFIG] Loaded config: {...}` or `[CONFIG] Failed to load config: ...`).
   - Logs when the service starts (e.g., `[INFO] LogWatcher started with error trace grouping.`).
   - Logs errors for invalid/missing log files (e.g., `[ERROR] Invalid or missing log file: ...`).
   - Logs n8n webhook activity (e.g., `[SEND] Sending error trace to n8n:` or `[ERROR] Failed to send to n8n: ...`).
   - Logs git blame errors (e.g., `[blame error] ...`).

2. **HTTP Requests to n8n Webhook**:

   - Sends JSON payloads to the configured `n8n_url` with:
     - `error_line`: The full error trace (string, possibly multi-line).
     - `error_detail`: A dictionary containing:
       - `file`: File path where the error occurred.
       - `line`: Line number of the error.
       - `vhost`: Apache virtual host file path (or `None`).
       - `git_remote`: Git repository remote URL (or `'unknown'`).
       - `error_line`: The error trace (same as top-level).
       - `blame`: Git blame info (dict with `author`, `email`, `commit`, `summary`, or `None`).

3. **Internal Caches**:

   - Populates in-memory caches (`vhost_cache`, `git_root_cache`, `git_remote_cache`, `git_blame_cache`) to store virtual host mappings, git repository roots, remote URLs, and blame information.

4. **Yields from** `tail_log` **Method**:

   - Yields multi-line error traces (strings) extracted from the Apache log file, grouped based on the `error_start_pattern` regex.

## 2. Examples

### Example 1: Basic Usage with Default Parameters

**Setup**:

- Create a `config.json` file:

  ```json
  {
    "log_file": "/var/log/apache2/error.log",
    "enabled": true,
    "n8n_url": "https://n8n.example.com/webhook"
  }
  ```
- Apache log file (`/var/log/apache2/error.log`) contains:

  ```
  [Tue Aug 05 21:29:00 2025] [error] PHP Fatal error: Undefined variable in /var/www/html/index.php on line 42
      Stack trace:
      #0 /var/www/html/index.php(42): some_function()
      #1 {main}
  ```

**Code**:

```python
watcher = LogWatcher()  # Uses default config_path='config.json', reload_interval=10
watcher.run()
```

**Output**:

- Console:

  ```
  [CONFIG] Loaded config: {'log_file': '/var/log/apache2/error.log', 'enabled': True, 'n8n_url': 'https://n8n.example.com/webhook'}
  [INFO] LogWatcher started with error trace grouping.
  [SEND] Sending error trace to n8n:
  ```
- HTTP POST to `https://n8n.example.com/webhook`:

  ```json
  {
    "error_line": "[Tue Aug 05 21:29:00 2025] [error] PHP Fatal error: Undefined variable in /var/www/html/index.php on line 42\n    Stack trace:\n    #0 /var/www/html/index.php(42): some_function()\n    #1 {main}",
    "error_detail": {
      "file": "/var/www/html/index.php",
      "line": 42,
      "vhost": "/etc/apache2/sites-enabled/000-default.conf",
      "git_remote": "git@github.com:example/repo.git",
      "error_line": "[Tue Aug 05 21:29:00 2025] [error] PHP Fatal error: Undefined variable in /var/www/html/index.php on line 42\n    Stack trace:\n    #0 /var/www/html/index.php(42): some_function()\n    #1 {main}",
      "blame": {
        "author": "John Doe",
        "email": "john@example.com",
        "commit": "a1b2c3d4",
        "summary": "Fix variable initialization"
      }
    }
  }
  ```

### Example 2: Custom Configuration and Missing Log File

**Setup**:

- `custom_config.json`:

  ```json
  {
    "log_file": "/var/log/apache2/nonexistent.log",
    "enabled": true,
    "n8n_url": "https://n8n.example.com/webhook"
  }
  ```

**Code**:

```python
watcher = LogWatcher(config_path='custom_config.json', reload_interval=30)
watcher.run()
```

**Output**:

- Console:

  ```
  [CONFIG] Loaded config: {'log_file': '/var/log/apache2/nonexistent.log', 'enabled': True, 'n8n_url': 'https://n8n.example.com/webhook'}
  [INFO] LogWatcher started with error trace grouping.
  [ERROR] Invalid or missing log file: /var/log/apache2/nonexistent.log
  ```
- No HTTP requests are sent because the log file is missing.

### Example 3: Disabled via Config

**Setup**:

- `config.json`:

  ```json
  {
    "log_file": "/var/log/apache2/error.log",
    "enabled": false,
    "n8n_url": "https://n8n.example.com/webhook"
  }
  ```
- Log file contains errors as in Example 1.

**Code**:

```python
watcher = LogWatcher(config_path='config.json', reload_interval=5)
watcher.run()
```

**Output**:

- Console:

  ```
  [CONFIG] Loaded config: {'log_file': '/var/log/apache2/error.log', 'enabled': False, 'n8n_url': 'https://n8n.example.com/webhook'}
  [INFO] LogWatcher started with error trace grouping.
  [INFO] Sending disabled via config.
  ```
- No HTTP requests are sent because `enabled` is `False`.

## 3. Code Quality and Suggestions for Improvement

### Code Quality Assessment

**Strengths**:

1. **Modularity**: The code is well-organized into a class with clear method responsibilities (e.g., `tail_log` for log reading, `send_to_n8n` for webhook communication, `get_project_info` for metadata extraction).
2. **Error Handling**: Catches and logs exceptions in critical areas (config loading, HTTP requests, git commands), preventing crashes.
3. **Efficiency**: Uses caching (`cachetools.TTLCache` for git data, persistent `vhost_cache`) to reduce redundant system calls and improve performance in high-traffic environments.
4. **Real-Time Log Tailing**: Implements a robust log tailing mechanism with error trace grouping, suitable for long-running services.
5. **Extensibility**: Configurable via JSON, with reload capability for dynamic updates.

**Weaknesses**:

1. **Missing Import**: The `fcntl` module is referenced in `tail_log` (`fcntl_wait_time`), but it’s not imported. This will cause a `NameError` on platforms where `fcntl` is available (e.g., Linux).
2. **Platform Dependency**: The code assumes a Unix-like environment (e.g., `subprocess.getoutput`, `fcntl`, Apache-specific paths like `/etc/apache2/sites-enabled`). It may fail on Windows or non-Apache setups.
3. **Hardcoded Paths**: The default `vhost_dir` (`/etc/apache2/sites-enabled`) is Apache-specific and not configurable.
4. **Security Risks**: Uses `subprocess.getoutput` with shell commands (e.g., `grep -l`), which is vulnerable to command injection if `file_path` contains malicious input.
5. **Limited Error Parsing**: The regex (`error_start_pattern`) may miss some error formats, and the file/line extraction (`in (.+?) on line (\d+)`) assumes a specific pattern.
6. **No Logging Framework**: Relies on `print` for logging, which lacks features like log levels, rotation, or centralized logging.
7. **No Configuration Validation**: Doesn’t validate required config keys (`log_file`, `n8n_url`, `enabled`), leading to silent failures if missing.
8. **No Graceful Shutdown**: The `run` loop is infinite and lacks a mechanism to stop cleanly (e.g., via signals).
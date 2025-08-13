import json
import subprocess
import os
import time
import requests
import re
import logging
import signal
from cachetools import TTLCache

class LogWatcher:
    """
    LogWatcher is a long-running Python service to monitor Apache error logs for PHP errors
    (Fatal error, Warning, Notice, Parse error, etc.) and forward enriched error details
    (including Git blame, vhost, and file location) to an n8n webhook.

    Key Features:
    - Tails Apache error logs in real-time.
    - Groups multi-line PHP stack traces.
    - Identifies file, line, vhost, Git remote, and blame information.
    - Forwards payload to n8n endpoint as JSON.
    - Uses persistent HTTP session and caching for efficiency.

    Caches:
    - vhost_cache (dict): Forever cached since vhost config rarely changes.
    - git_root_cache (TTLCache): Cached per directory, TTL 1 hour.
    - git_remote_cache (TTLCache): Cached per directory, TTL 1 hour.
    - git_blame_cache (TTLCache): Cached per file and line, TTL 1 hour.

    Usage:
        watcher = LogWatcher(config_path='config.json', reload_interval=10)
        watcher.run()
    """

    def __init__(self, config_path='config.json', reload_interval=10):
        """
        Initializes LogWatcher with config and caches.

        Args:
            config_path (str): Path to JSON config file.
            reload_interval (int): Seconds between config reloads.

        Raises:
            ValueError: If config is invalid or missing required keys.
        """
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler('logwatcher.log'),
                logging.StreamHandler()
            ]
        )
        self.config_path = config_path
        self.reload_interval = reload_interval
        self.config = {}
        self.last_config_load_time = 0
        self.running = True
        self.load_config()
        self.error_start_pattern = re.compile(
            r'(PHP (Fatal error|Warning|Notice|Parse error)|\[error\])', re.IGNORECASE
        )
        self.vhost_cache = {}  # Forever cache
        self.git_root_cache = TTLCache(maxsize=1000, ttl=3600)  # TTL 1 hour
        self.git_remote_cache = TTLCache(maxsize=1000, ttl=3600)  # TTL 1 hour
        self.git_blame_cache = TTLCache(maxsize=5000, ttl=3600)  # TTL 1 hour
        self.session = requests.Session()
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        self.check_dependencies()

    def signal_handler(self, signum, frame):
        """
        Handles shutdown signals (SIGINT, SIGTERM) for graceful exit.

        Args:
            signum (int): Signal number.
            frame: Current stack frame.
        """
        self.logger.info("Received shutdown signal, stopping...")
        self.running = False
        self.session.close()

    def check_dependencies(self):
        """
        Checks for required dependencies (git, vhost directory).
        """
        try:
            subprocess.run(['git', '--version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.error("Git is not installed or not in PATH")
        vhost_dir = self.config.get('vhost_dir', '/etc/apache2/sites-enabled')
        if not os.path.exists(vhost_dir):
            self.logger.warning(f"Vhost directory does not exist: {vhost_dir}")

    def load_config(self):
        """
        Loads JSON config from disk into self.config.
        Expected keys: 'log_file', 'enabled', 'n8n_url', 'vhost_dir' (optional).

        Raises:
            ValueError: If required keys are missing or invalid.
        """
        try:
            with open(self.config_path) as f:
                self.config = json.load(f)
            required_keys = {'log_file', 'enabled', 'n8n_url'}
            missing_keys = required_keys - set(self.config.keys())
            if missing_keys:
                raise ValueError(f"Missing required config keys: {missing_keys}")
            if not isinstance(self.config['enabled'], bool):
                raise ValueError("'enabled' must be a boolean")
            if not os.path.isfile(self.config['log_file']):
                raise ValueError(f"Log file does not exist: {self.config['log_file']}")
            self.last_config_load_time = time.time()
            self.logger.info(f"Loaded config: {self.config}")
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            self.config = {}

    def config_needs_reload(self):
        """
        Determines if config should be reloaded based on time interval.

        Returns:
            bool: True if reload is due.
        """
        return (time.time() - self.last_config_load_time) >= self.reload_interval

    def send_to_n8n(self, error_trace):
        """
        Sends the error trace to the n8n webhook defined in config.

        Args:
            error_trace (str): Full PHP error message trace (possibly multi-line).
        """
        n8n_url = self.config.get("n8n_url")
        if not n8n_url:
            self.logger.warning("n8n URL not set in config")
            return

        try:
            error_detail = self.get_project_info(error_trace)
            self.logger.info("Sending error trace to n8n")
            self.session.post(
                n8n_url,
                json={"error_line": error_trace, "error_detail": error_detail},
                timeout=2
            )
        except Exception as e:
            self.logger.error(f"Failed to send to n8n: {e}")

    def tail_log(self):
        """
        Generator that tails the Apache error log and yields grouped PHP error traces.

        Yields:
            str: Multi-line PHP error trace strings.
        """
        log_file = self.config.get("log_file")
        if not log_file or not os.path.isfile(log_file):
            self.logger.error(f"Invalid or missing log file: {log_file}")
            return

        with open(log_file, 'r') as f:
            f.seek(0, os.SEEK_END)
            current_trace = []
            while self.running:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue

                line = line.strip()
                if self.error_start_pattern.search(line):
                    if current_trace:
                        yield "\n".join(current_trace)
                        current_trace = []
                current_trace.append(line)

                start_time = time.time()
                timeout = 2  # seconds
                while self.running:
                    next_line = f.readline()
                    if not next_line:
                        if time.time() - start_time >= timeout:
                            if current_trace:
                                yield "\n".join(current_trace)
                                current_trace = []
                            break
                        time.sleep(0.2)
                        continue
                    next_line = next_line.strip()
                    current_trace.append(next_line)
                    start_time = time.time()

    def run(self):
        """
        Starts the log watcher loop, monitoring Apache error logs and sending PHP errors to n8n.
        """
        self.logger.info("LogWatcher started with PHP error trace grouping")
        for error_trace in self.tail_log():
            if not self.running:
                break
            if self.config_needs_reload():
                self.load_config()
            if not self.config.get("enabled", False):
                self.logger.info("Sending disabled via config")
                continue
            self.send_to_n8n(error_trace)

    def find_vhost_for_path(self, file_path):
        """
        Finds the Apache vhost config for a given file path.

        Args:
            file_path (str): Full file path of the error file.

        Returns:
            str | None: Path to matching vhost file, or None if not found.
        """
        vhost_dir = self.config.get('vhost_dir', '/etc/apache2/sites-enabled')
        if file_path in self.vhost_cache:
            return self.vhost_cache[file_path]

        search_path = os.path.dirname(file_path)
        found_vhost = None

        while True:
            try:
                result = subprocess.run(
                    ['grep', '-l', search_path, f'{vhost_dir}/*'],
                    capture_output=True,
                    text=True,
                    check=False
                )
                found_vhost = result.stdout.strip()
                if found_vhost:
                    break
            except subprocess.CalledProcessError:
                pass
            parent_path = os.path.dirname(search_path)
            if parent_path == search_path or parent_path == '/':
                break
            search_path = parent_path

        self.vhost_cache[file_path] = found_vhost
        return found_vhost

    def get_project_info(self, error_line):
        """
        Extracts file, line number, vhost, git blame, and repo info for a PHP error.

        Args:
            error_line (str): Line or trace containing file path and line number.

        Returns:
            dict | None: Structured metadata or None if file not found.
        """
        match = re.search(r'in (.+?) on line (\d+)', error_line)
        if not match:
            return None

        file_path, line_number = match.groups()
        file_path = file_path.strip()
        line_number = int(line_number)
        dir_path = os.path.abspath(os.path.dirname(file_path))

        vhost = self.find_vhost_for_path(file_path)

        if dir_path in self.git_root_cache:
            repo_root = self.git_root_cache[dir_path]
        else:
            try:
                repo_root = subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"],
                    cwd=dir_path,
                    text=True
                ).strip()
            except subprocess.CalledProcessError:
                repo_root = None
            self.git_root_cache[dir_path] = repo_root

        if dir_path in self.git_remote_cache:
            git_remote = self.git_remote_cache[dir_path]
        else:
            try:
                git_remote = subprocess.check_output(
                    ["git", "config", "--get", "remote.origin.url"],
                    cwd=dir_path,
                    text=True
                ).strip() or 'unknown'
            except subprocess.CalledProcessError:
                git_remote = 'unknown'
            self.git_remote_cache[dir_path] = git_remote

        blame_key = f"{file_path}:{line_number}"
        if blame_key in self.git_blame_cache:
            blame = self.git_blame_cache[blame_key]
        else:
            blame = self.get_git_blame(file_path, line_number, repo_root)
            self.git_blame_cache[blame_key] = blame

        return {
            "file": file_path,
            "line": line_number,
            "vhost": vhost.strip() if vhost else None,
            "git_remote": git_remote,
            "error_line": error_line.strip(),
            "blame": blame
        }

    def get_git_blame(self, file_path, line_number, repo_path=None):
        """
        Runs `git blame` on a specific line to get commit and author info.

        Args:
            file_path (str): Full path to the file.
            line_number (int): Line number for blame.
            repo_path (str | None): Git repository root directory.

        Returns:
            dict | None: Author, email, summary, commit hash, or None if unavailable.
        """
        if not repo_path:
            return None

        try:
            rel_path = os.path.relpath(file_path, repo_path)
            blame_output = subprocess.check_output(
                ["git", "blame", "-L", f"{line_number},{line_number}", "--porcelain", rel_path],
                cwd=repo_path,
                text=True
            )

            blame = {
                "author": None,
                "email": None,
                "commit": None,
                "summary": None
            }

            for line in blame_output.splitlines():
                if line.startswith("author "):
                    blame["author"] = line[7:]
                elif line.startswith("author-mail "):
                    blame["email"] = line[12:].strip("<>")
                elif line.startswith("summary "):
                    blame["summary"] = line[8:]
                elif re.match(r"^[a-f0-9]{40}", line):
                    blame["commit"] = line.split()[0][:8]

            return blame

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Git blame failed: {e}")
            return None

if __name__ == '__main__':
    watcher = LogWatcher(config_path='config.json', reload_interval=10)
    watcher.run()

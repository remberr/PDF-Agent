"""Launch the image in external database mode or supervise the embedded database."""

import fcntl
import os
import pwd
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


DISK = Path('/data')
STORAGE = DISK / 'pdf-agent-postgres'
CLUSTER = STORAGE / 'pg17'
SOCKET = Path('/run/pdf-agent-postgres')
PG_BIN = Path('/usr/lib/postgresql/17/bin')
DB_NAME = 'pdf_agent'
DB_ADDRESS = '127.0.0.1'
DB_PORT = '5432'
MIGRATION_ROLE = 'pdf_agent_migrate'
APP_ROLE = 'pdf_agent_runtime'
MIB = 1024 * 1024
MIN_START_FREE = 192 * MIB
MIN_ACTIVE_FREE = 96 * MIB

POSTGRES_SETTINGS = {
    'listen_addresses': DB_ADDRESS,
    'port': DB_PORT,
    'unix_socket_directories': str(SOCKET),
    'hba_file': '/opt/pdf-agent/postgres_hba.conf',
    'password_encryption': 'scram-sha-256',
    'max_connections': '12',
    'shared_buffers': '32MB',
    'work_mem': '1MB',
    'maintenance_work_mem': '16MB',
    'autovacuum_work_mem': '8MB',
    'max_parallel_workers': '0',
    'jit': 'off',
    'min_wal_size': '32MB',
    'max_wal_size': '64MB',
    'log_min_messages': 'log',
    'log_min_error_statement': 'panic',
    'log_error_verbosity': 'terse',
}

EMBEDDED_DEFAULTS = {
    'DB_POOL_SIZE': '3',
    'DB_MAX_OVERFLOW': '0',
    'OMP_NUM_THREADS': '1',
    'MKL_NUM_THREADS': '1',
    'OPENBLAS_NUM_THREADS': '1',
    'TOKENIZERS_PARALLELISM': 'false',
    'HF_HUB_OFFLINE': '1',
    'PDF_AGENT_MAX_CONCURRENT_QUESTIONS': '1',
    'PDF_AGENT_MAX_CONCURRENT_UPLOADS': '1',
    'PDF_AGENT_MAX_QUESTION_CHARS': '2000',
    'PDF_AGENT_MAX_PDF_PAGES': '40',
    'PDF_AGENT_MAX_PDF_TEXT_CHARS': '48000',
    'PDF_AGENT_MAX_PDF_CHUNKS': '48',
    'PDF_AGENT_MAX_UPLOAD_FILES': '2',
    'PDF_AGENT_MAX_FILE_BYTES': str(10 * MIB),
    'PDF_AGENT_MAX_BATCH_BYTES': str(20 * MIB),
}


class StartupError(RuntimeError):
    """A fixed diagnostic that is safe to log."""


def announce(message: str) -> None:
    print(f'container: {message}', flush=True)


def launch(command: list[str], user: str, **kwargs) -> subprocess.Popen:
    account = pwd.getpwnam(user)
    environment = dict(kwargs.pop('env', os.environ))
    environment.update(HOME=account.pw_dir, USER=user, LOGNAME=user)
    return subprocess.Popen(command, user=account.pw_uid, group=account.pw_gid,
                            extra_groups=[], env=environment, **kwargs)


def shutdown(process: subprocess.Popen | None, requested_signal: int, timeout: int) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(requested_signal)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        announce('shutdown deadline exceeded; stopping child')
        process.kill()
        process.wait()


def checked_directory(path: Path, owner: int, mode: int) -> None:
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        pass
    else:
        os.chown(path, owner, -1)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
        raise StartupError('database directory has unsafe ownership or permissions')


def check_disk() -> None:
    mounts = Path('/proc/self/mountinfo').read_text().splitlines()
    if DISK.is_symlink() or not any(record.split()[4] == str(DISK) for record in mounts):
        raise StartupError('embedded PostgreSQL requires a persistent mount at /data')
    if shutil.disk_usage(DISK).free < MIN_START_FREE:
        raise StartupError('persistent disk has less than 192 MiB free; database startup halted')


def application_env() -> dict[str, str]:
    environment = dict(os.environ)
    for key, value in EMBEDDED_DEFAULTS.items():
        environment.setdefault(key, value)
    origin = environment.get('RENDER_EXTERNAL_URL')
    if origin:
        environment.setdefault('SESSION_BROWSER_ORIGINS', origin.rstrip('/'))
    return environment


def database_url(role: str, password: str) -> str:
    return f'postgresql+psycopg://{role}:{password}@{DB_ADDRESS}:{DB_PORT}/{DB_NAME}'


def admin_env() -> dict[str, str]:
    # Ignore PGHOST, PGOPTIONS, provider secrets, and other application settings.
    return {'PATH': os.defpath, 'LANG': 'C.UTF-8'}


class EmbeddedPostgres:
    def __init__(self) -> None:
        self.stopping = threading.Event()
        self.database: subprocess.Popen | None = None
        self.application: subprocess.Popen | None = None

    def handle_stop(self, _signum: int, _frame) -> None:
        self.stopping.set()

    def stage(self, label: str, command: list[str], user: str, timeout: int, *,
              env: dict[str, str], sql: str | None = None, quiet: bool = False) -> None:
        if self.stopping.is_set():
            raise StartupError('startup interrupted by shutdown')
        output = subprocess.DEVNULL if quiet else None
        process = launch(command, user, env=env, text=True, stdout=output, stderr=output,
                         stdin=subprocess.PIPE if sql is not None else subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + timeout
            while not self.stopping.is_set() and time.monotonic() < deadline:
                try:
                    process.communicate(input=sql, timeout=0.2)
                except subprocess.TimeoutExpired:
                    sql = None  # communicate retains and resumes any pending input.
                    continue
                if process.returncode == 0:
                    return
                break
            raise StartupError(f'{label} failed, timed out, or was interrupted')
        finally:
            shutdown(process, signal.SIGTERM, 3)

    def initialize(self) -> None:
        pg_user = pwd.getpwnam('postgres')
        checked_directory(SOCKET, pg_user.pw_uid, 0o700)
        if CLUSTER.exists() or CLUSTER.is_symlink():
            checked_directory(CLUSTER, pg_user.pw_uid, 0o700)
            if (CLUSTER / 'PG_VERSION').read_text().strip() != '17':
                raise StartupError('embedded cluster major version mismatch')
            return
        staging = Path(tempfile.mkdtemp(prefix='init-', dir=STORAGE))
        os.chown(staging, pg_user.pw_uid, pg_user.pw_gid)
        try:
            self.stage('cluster initialization', [str(PG_BIN / 'initdb'), '-D', str(staging),
                       '--username=postgres', '--auth-local=peer', '--auth-host=reject',
                       '--encoding=UTF8', '--locale=C.UTF-8', '--data-checksums'],
                       'postgres', 60, env=admin_env(), quiet=True)
            os.rename(staging, CLUSTER)
            fd = os.open(STORAGE, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def wait_for_database(self) -> None:
        deadline = time.monotonic() + 40
        assert self.database is not None
        while self.database.poll() is None and not self.stopping.is_set() and time.monotonic() < deadline:
            with launch([str(PG_BIN / 'pg_isready'), '-h', str(SOCKET), '-p', DB_PORT,
                         '-d', 'postgres', '-U', 'postgres', '-t', '1'], 'postgres',
                        env=admin_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as probe:
                if probe.wait(timeout=3) == 0:
                    return
            self.stopping.wait(0.2)
        raise StartupError('embedded PostgreSQL did not become ready')

    def admin(self, label: str, database: str, sql: str) -> None:
        self.stage(label, [str(PG_BIN / 'psql'), '-X', '-q', '-h', str(SOCKET),
                           '-p', DB_PORT, '-d', database, '-v', 'ON_ERROR_STOP=1'],
                   'postgres', 15, env=admin_env(), sql=sql, quiet=True)

    def provision(self) -> dict[str, str]:
        # Passwords are fresh lowercase hex from the OS RNG. Send SQL on stdin,
        # never argv or logs. Only the SCRAM verifiers survive a restart.
        migrate_password, app_password = secrets.token_hex(32), secrets.token_hex(32)
        self.admin('database role provisioning', 'postgres', rf"""
SELECT 'CREATE ROLE {MIGRATION_ROLE}' WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = '{MIGRATION_ROLE}') \gexec
SELECT 'CREATE ROLE {APP_ROLE}' WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') \gexec
ALTER ROLE {MIGRATION_ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    CONNECTION LIMIT 2 PASSWORD '{migrate_password}';
ALTER ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    CONNECTION LIMIT 4 PASSWORD '{app_password}';
SELECT 'CREATE DATABASE {DB_NAME} OWNER {MIGRATION_ROLE}' WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}') \gexec
REVOKE ALL ON DATABASE {DB_NAME} FROM PUBLIC;
GRANT CONNECT ON DATABASE {DB_NAME} TO {APP_ROLE};
""")
        self.admin('vector extension provisioning', DB_NAME, f"""
CREATE EXTENSION IF NOT EXISTS vector;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO {APP_ROLE};
""")
        migration_env = admin_env()
        migration_env['DATABASE_URL'] = database_url(MIGRATION_ROLE, migrate_password)
        self.stage('Alembic upgrade', [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                   'postgres', 90, env=migration_env, quiet=True)
        self.admin('application grants', DB_NAME, f"""
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {APP_ROLE};
ALTER ROLE {MIGRATION_ROLE} WITH NOLOGIN PASSWORD NULL;
""")
        environment = application_env()
        environment['DATABASE_URL'] = database_url(APP_ROLE, app_password)
        return environment

    def run(self, command: list[str]) -> int:
        signal.signal(signal.SIGTERM, self.handle_stop)
        signal.signal(signal.SIGINT, self.handle_stop)
        check_disk()
        checked_directory(STORAGE, 0, 0o755)
        fd = os.open(STORAGE / '.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise StartupError('persistent cluster is already in use') from None
            try:
                self.initialize()
                settings = [part for key, value in POSTGRES_SETTINGS.items() for part in ('-c', f'{key}={value}')]
                self.database = launch([str(PG_BIN / 'postgres'), '-D', str(CLUSTER), *settings],
                                       'postgres', env=admin_env())
                self.wait_for_database()
                environment = self.provision()
                free_mib = shutil.disk_usage(DISK).free // MIB
                announce(f'local PostgreSQL and schema ready; persistent disk free {free_mib} MiB')
                self.application = launch(command, 'appuser', env=environment)
                while not self.stopping.wait(1):
                    if self.application.poll() is not None or self.database.poll() is not None:
                        raise StartupError('application or PostgreSQL exited unexpectedly')
                    if shutil.disk_usage(DISK).free < MIN_ACTIVE_FREE:
                        raise StartupError('persistent disk reserve reached; stopping writes')
                return 0
            finally:
                shutdown(self.application, signal.SIGTERM, 12)
                shutdown(self.database, signal.SIGINT, 12)  # PostgreSQL fast, clean shutdown.


def main() -> int:
    render = os.environ.get('RENDER') == 'true'
    mode = os.environ.get('PDF_AGENT_DATABASE_MODE', 'embedded' if render else 'external')
    command = sys.argv[1:] or [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0',
                              '--port', os.environ.get('PORT', '8000'), '--no-access-log',
                              '--workers', '1', '--timeout-graceful-shutdown', '10']
    if mode == 'external':
        if os.geteuid() == 0:
            account = pwd.getpwnam('appuser')
            os.environ.update(HOME=account.pw_dir, USER=account.pw_name, LOGNAME=account.pw_name)
            os.setgroups([])
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
        os.execvp(command[0], command)
    if mode != 'embedded':
        raise StartupError('invalid PDF_AGENT_DATABASE_MODE')
    return EmbeddedPostgres().run(command)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except StartupError as error:
        announce(str(error))
        sys.exit(1)
    except (OSError, subprocess.SubprocessError) as error:
        announce(f'container startup or supervision failed ({type(error).__name__})')
        sys.exit(1)

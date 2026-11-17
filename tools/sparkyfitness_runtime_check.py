#!/usr/bin/env python3
"""Exercise the published package with synthetic data on an ephemeral CI runner."""
import base64
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = "mochilab-sparkyfitness"
EMAIL = "package-smoke@example.invalid"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6lAAAAABJRU5ErkJggg==")
UPLOAD = "/app/SparkyFitnessServer/uploads/food_images/package-smoke.png"
RESULTS = []


def passed(name, **details):
    RESULTS.append({"check": name, "status": "pass", **details})
    print("PASS", name, json.dumps(details), flush=True)


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, payload=None, content_type=None, raw=False):
        headers = {"Origin": self.base}
        if payload is not None:
            if content_type is None:
                payload = json.dumps(payload).encode()
                content_type = "application/json"
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=payload, headers=headers)
        try:
            with self.opener.open(request, timeout=180) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            # Only synthetic test accounts exist here. Never log cookies or full responses.
            raise RuntimeError(f"HTTP {error.code} at {path}: {error.read(600).decode(errors='replace')}") from None
        return body if raw else json.loads(body)

    def login(self, email, password):
        self.request("/api/auth/sign-in/email", {"email": email, "password": password})
        session = self.request("/api/auth/get-session")
        assert session["user"]["email"] == email, "Wrong authenticated account"


class Instance:
    def __init__(self, folder, credentials):
        self.folder = folder
        self.project = "sf-smoke-" + uuid.uuid4().hex[:12]
        self.env = dict(os.environ, **credentials, APP_DATA_DIR=str(folder),
                        DEVICE_DOMAIN_NAME="localhost", APP_PROXY_PORT="3019",
                        APP_MOCHILAB_SPARKYFITNESS_TOR_ORIGIN="")
        data = folder / "data"
        data.mkdir(parents=True)
        for name in ("uploads", "backup", "upload-tmp", "postgres"):
            (data / name).mkdir()
        # These are newly created synthetic directories on the disposable runner only.
        subprocess.run(["sudo", "chown", "-R", "1000:1000", str(data)], check=True)
        package = yaml.safe_load((ROOT / APP / "docker-compose.yml").read_text())
        package["services"].pop("app_proxy")  # Native umbreld gateway is not present in CI.
        for service, settings in package["services"].items():
            settings["networks"] = {"default": {"aliases": [APP + "_" + service + "_1"]}}
        package["services"]["frontend"]["ports"] = ["127.0.0.1::80"]
        self.compose_file = folder / "compose.yml"
        self.compose_file.write_text(yaml.safe_dump(package, sort_keys=False))

    def compose(self, *args, input=None, timeout=480):
        result = subprocess.run(["docker", "compose", "-p", self.project,
                                 "-f", str(self.compose_file), *args], env=self.env,
                                input=input, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError("compose " + " ".join(args[:2]) + ": " +
                               result.stderr.decode(errors="replace")[-4000:])
        return result.stdout

    def start(self):
        self.compose("up", "-d", "--wait", "--wait-timeout", "360")
        address = self.compose("port", "frontend", "80").decode().strip()
        self.base = "http://" + address
        probe = Client(self.base)
        deadline = time.monotonic() + 60
        while True:
            try:
                probe.request("/api/health/ready")
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)
        page = probe.request("/", raw=True)
        assert b"<html" in page.lower(), "Frontend did not serve HTML"

    def sql(self, statement):
        return self.compose("exec", "-T", "db", "psql", "-U", "sparky", "-d",
                            "sparkyfitness_db", "-v", "ON_ERROR_STOP=1", "-At",
                            input=statement.encode()).decode().strip()

    def write_upload(self, content):
        js = "const fs=require('fs');fs.mkdirSync(require('path').dirname(process.argv[1]),{recursive:true});fs.writeFileSync(process.argv[1],Buffer.from(process.argv[2],'base64'))"
        self.compose("exec", "-T", "server", "node", "-e", js, UPLOAD,
                     base64.b64encode(content).decode())

    def check_data(self, client):
        assert self.sql("SELECT value FROM public.package_smoke_canary WHERE id=1;") == "before-backup"
        assert client.request("/uploads/food_images/package-smoke.png", raw=True) == PNG

    def close(self):
        self.compose("down", "--volumes", "--remove-orphans", timeout=120)


def restore(client, archive):
    boundary = "sf-smoke-" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"backupFile\"; filename=\"synthetic-backup.tar.gz\"\r\n"
            "Content-Type: application/gzip\r\n\r\n").encode() + archive + f"\r\n--{boundary}--\r\n".encode()
    response = client.request("/api/admin/backup/restore", body, "multipart/form-data; boundary=" + boundary)
    assert "successfully" in response["message"].lower(), "Restore did not complete"


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("RUNNER_TEMP"):
        raise SystemExit("This test runs only on a disposable GitHub Actions runner; never point it at an existing app.")
    credentials = {"APP_MOCHILAB_SPARKYFITNESS_" + key: secrets.token_hex(32)
                   for key in ("DB_PASSWORD", "APP_DB_PASSWORD", "API_ENCRYPTION_KEY", "BETTER_AUTH_SECRET")}
    password = secrets.token_urlsafe(24)
    instances = []
    report = Path(os.environ["RUNNER_TEMP"]) / "sparkyfitness-runtime-result.json"
    status = "failed"
    with tempfile.TemporaryDirectory(prefix="sparkyfitness-smoke-", dir=os.environ["RUNNER_TEMP"]) as temporary:
        try:
            first = Instance(Path(temporary) / "original", credentials)
            instances.append(first)
            first.start()
            count = int(first.sql("SELECT count(*) FROM system.schema_migrations;"))
            assert count > 100, "Migration set incomplete"
            passed("fresh_start_and_migrations", migrations=count)
            client = Client(first.base)
            client.request("/api/auth/sign-up/email", {"name": "Synthetic package test", "email": EMAIL, "password": password})
            client = Client(first.base)
            client.login(EMAIL, password)
            client.request("/api/admin/backup/settings")
            passed("first_account_admin_and_password_login")
            first.sql("CREATE TABLE public.package_smoke_canary(id int PRIMARY KEY, value text NOT NULL); INSERT INTO public.package_smoke_canary VALUES(1,'before-backup');")
            first.write_upload(PNG)
            first.check_data(client)
            backup = client.request("/api/admin/backup/manual", {})
            archive = client.request("/api/admin/backup/download/" + urllib.parse.quote(backup["fileName"], safe=""), raw=True)
            assert len(archive) > 1000, "Backup is empty"
            passed("application_logical_backup_and_upload_archive", bytes=len(archive), sha256=hashlib.sha256(archive).hexdigest())
            first.sql("UPDATE public.package_smoke_canary SET value='after-backup';")
            first.write_upload(b"synthetic content after backup")
            restore(client, archive)
            client = Client(first.base)
            client.login(EMAIL, password)
            first.check_data(client)
            passed("in_place_restore_reverts_database_and_upload")
            first.compose("restart", "db", "server", "frontend", "garmin")
            first.start()
            client = Client(first.base)
            client.login(EMAIL, password)
            first.check_data(client)
            assert int(first.sql("SELECT count(*) FROM system.schema_migrations;")) == count
            passed("restart_persistence_and_idempotent_migrations")
            recovered = Instance(Path(temporary) / "recovered", credentials)
            instances.append(recovered)
            recovered.start()
            bootstrap = Client(recovered.base)
            bootstrap.request("/api/auth/sign-up/email", {"name": "Synthetic recovery admin", "email": "recovery@example.invalid", "password": password})
            bootstrap = Client(recovered.base)
            bootstrap.login("recovery@example.invalid", password)
            restore(bootstrap, archive)
            client = Client(recovered.base)
            client.login(EMAIL, password)
            recovered.check_data(client)
            assert recovered.sql('SELECT count(*) FROM "user" WHERE email=\'recovery@example.invalid\';') == "0"
            passed("fresh_instance_recovery_with_preserved_test_secrets")
            status = "passed"
        finally:
            cleanup_errors = []
            for instance in reversed(instances):
                if status != "passed":
                    try:
                        # Synthetic-only containers; never read production or owner logs.
                        logs = instance.compose("logs", "--tail", "50", "db", "server", "frontend").decode(errors="replace")
                        for secret in (*credentials.values(), password):
                            logs = logs.replace(secret, "<synthetic-secret>")
                        print(logs[-12000:], flush=True)
                    except Exception:
                        pass
                try:
                    instance.close()
                except Exception as error:
                    cleanup_errors.append(str(error))
            report.write_text(json.dumps({"status": status, "checks": RESULTS,
                                         "cleanup_errors": cleanup_errors,
                                         "limits": ["HTTP API sign-in through packaged nginx; browser UI and native umbreld gateway not exercised", "Synthetic-only data and secrets; real Umbrel seed recovery and Denny PG15 migration not exercised", "Single amd64 runner; arm64 images checked separately"]}, indent=2) + "\n")
            subprocess.run(["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", temporary], check=True)
            if cleanup_errors:
                raise RuntimeError("Synthetic runner cleanup failed: " + "; ".join(cleanup_errors))
    print("SPARKYFITNESS_RUNTIME_AND_RESTORE_OK", flush=True)


if __name__ == "__main__":
    main()

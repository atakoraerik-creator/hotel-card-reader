# Web interface: local hosting and deployment

The web interface is a server-rendered FastAPI application. It is separate from the PySide6
desktop reader, but both live in the same repository and share the read-only diagnostics code.

## What it does

- Manages rooms, guests, card records, users, and hotel settings.
- Records an audit trail for sign-in and front-desk actions.
- Issues **simulated** card records only. It does not write, clone, erase, or reset a physical card.
- Shows encoder bridge status through the read-only `simulated`, `pcsc`, or `vendor` adapter.

Card issuance is intentionally labelled as simulation. Do not describe it as physical encoding.

## Local demo on Windows

From the repository root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
Copy-Item .env.example .env
```

Generate a session secret and put it in `.env` as `DOORCARD_WEB_SECRET`:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Start the server:

```powershell
.\.venv\Scripts\python.exe -m doorcard.web
```

Open:

```text
http://127.0.0.1:8000
```

The first start creates `data/doorcard-web.db` and, with `DOORCARD_SEED_DEMO=true`, seeds demo
data. To prepare the database without starting the server:

```powershell
.\.venv\Scripts\python.exe -m doorcard.web.manage init-db
```

Demo accounts:

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@horizon.test` | `Admin!23456` |
| Receptionist | `reception@horizon.test` | `Reception!23456` |

Change or remove demo accounts before any non-local use. Set `DOORCARD_SEED_DEMO=false` outside
local evaluation.

Stop the server with `Ctrl+C`.

## Local configuration

The application reads `.env` from the repository root. Supported values:

| Variable | Purpose |
|---|---|
| `DOORCARD_WEB_ENV` | `development` or `production` |
| `DOORCARD_WEB_SECRET` | Session signing secret; required in production |
| `DOORCARD_WEB_HOST` | Bind address; default `127.0.0.1` |
| `DOORCARD_WEB_PORT` | Bind port; default `8000` |
| `DOORCARD_WEB_ALLOWED_HOSTS` | Comma-separated Host allow-list |
| `DOORCARD_WEB_SECURE_COOKIE` | `true` behind HTTPS |
| `DOORCARD_WEB_SESSION_MAX_AGE` | Session lifetime in seconds |
| `DOORCARD_DATABASE_URL` | SQLAlchemy database URL |
| `DOORCARD_SEED_DEMO` | Seed local demo data |
| `DOORCARD_ENCODER_MODE` | `simulated`, `pcsc`, or `vendor` |
| `DOORCARD_HOTEL_NAME` | Initial hotel name |
| `DOORCARD_LOGIN_MAX_ATTEMPTS` | Failed sign-ins before throttling |
| `DOORCARD_LOGIN_WINDOW_SECONDS` | Throttle window |

For a local SQLite file, use an absolute path in production:

```text
DOORCARD_DATABASE_URL=sqlite:////srv/doorcard/data/doorcard-web.db
```

## LAN access

Only do this on a trusted network.

1. Set `DOORCARD_WEB_HOST=0.0.0.0`.
2. Add the machine name or IP to `DOORCARD_WEB_ALLOWED_HOSTS`, for example
   `127.0.0.1,localhost,192.168.1.50`.
3. Allow TCP port `8000` in Windows Firewall for that private network only.
4. Open `http://192.168.1.50:8000` from another device.

LAN HTTP is not suitable for sensitive data outside a trusted network. Prefer HTTPS through a
reverse proxy.

## Online deployment

Use a small Linux VPS or container host. Keep the database and application on the same trusted
server. The web process must have one worker while using SQLite; use a server database before
scaling to multiple workers.

### Option 1: systemd + Caddy

```bash
sudo mkdir -p /srv/doorcard
sudo useradd --system --home /srv/doorcard --shell /usr/sbin/nologin doorcard
sudo chown -R doorcard:doorcard /srv/doorcard
```

Copy the project to `/srv/doorcard/app`, then:

```bash
cd /srv/doorcard/app
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-web.txt
```

Create `/srv/doorcard/app/.env`:

```text
DOORCARD_WEB_ENV=production
DOORCARD_WEB_SECRET=<long-random-secret>
DOORCARD_WEB_HOST=127.0.0.1
DOORCARD_WEB_PORT=8000
DOORCARD_WEB_ALLOWED_HOSTS=cards.example.com
DOORCARD_WEB_SECURE_COOKIE=true
DOORCARD_DATABASE_URL=sqlite:////srv/doorcard/data/doorcard-web.db
DOORCARD_SEED_DEMO=false
DOORCARD_ENCODER_MODE=simulated
```

Create the administrator account non-interactively only through the supported CLI prompt:

```bash
.venv/bin/python -m doorcard.web.manage create-admin \
  --email admin@example.com --username admin --name "Hotel Administrator"
```

The prompt reads the password without echoing it.

Systemd unit `/etc/systemd/system/doorcard-web.service`:

```ini
[Unit]
Description=DoorCard web interface
After=network.target

[Service]
Type=simple
User=doorcard
Group=doorcard
WorkingDirectory=/srv/doorcard/app
EnvironmentFile=/srv/doorcard/app/.env
ExecStart=/srv/doorcard/app/.venv/bin/python -m doorcard.web
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now doorcard-web
sudo systemctl status doorcard-web
```

Caddy `/etc/caddy/Caddyfile`:

```caddyfile
cards.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}
```

Caddy obtains and renews HTTPS certificates automatically. Set
`DOORCARD_WEB_SECURE_COOKIE=true` only after HTTPS is working.

### Option 2: Docker Compose

Create `.env` beside `docker-compose.yml`:

```text
DOORCARD_WEB_SECRET=<long-random-secret>
DOORCARD_WEB_ALLOWED_HOSTS=localhost,127.0.0.1
```

Build and start:

```bash
docker compose up -d --build
docker compose logs -f web
```

Open `http://127.0.0.1:8000`.

The compose file disables secure cookies for local HTTP testing. For public HTTPS, terminate TLS
with a reverse proxy, set `DOORCARD_WEB_ALLOWED_HOSTS` to the real hostname, and set
`DOORCARD_WEB_SECURE_COOKIE=true`.

### Database backup

For SQLite, stop the service briefly and copy the database file:

```bash
sudo systemctl stop doorcard-web
sudo cp /srv/doorcard/data/doorcard-web.db /srv/doorcard/backups/doorcard-web-$(date +%F).db
sudo systemctl start doorcard-web
```

Test restore procedures before relying on backups. Never commit `.env`, database files, or backups
to Git.

## Security checklist

- Set a unique `DOORCARD_WEB_SECRET`; never commit it.
- Use HTTPS and `DOORCARD_WEB_SECURE_COOKIE=true` for anything beyond localhost.
- Set `DOORCARD_WEB_ENV=production` and `DOORCARD_SEED_DEMO=false`.
- Set `DOORCARD_WEB_ALLOWED_HOSTS` to the actual domain or IP.
- Use least-privilege accounts and disable departed staff promptly.
- Keep the database on a private volume and back it up.
- Restrict the encoder bridge to a trusted machine. The web bridge is read-only, but it should
  still not be exposed to untrusted users.
- Do not port-forward from the public internet until HTTPS, secrets, backups, and access ownership
  are in place.

## Deployment limits

- No physical card writes are implemented.
- No Brassco SDK/API is known or assumed; `vendor` mode requires an existing documented adapter.
- SQLite is appropriate for a single small property and one web worker. Use PostgreSQL for
  multiple workers or higher concurrency.
- The in-memory login throttle resets when the process restarts. Use a shared rate limiter for
  multi-instance deployments.

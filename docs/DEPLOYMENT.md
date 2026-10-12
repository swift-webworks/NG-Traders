# Deployment (Ubuntu VPS, Gunicorn, Nginx, PostgreSQL, HTTPS)

> These steps were **not executed** in the development environment (no VPS available). They are standard
> and the configuration files are provided, but follow them carefully and verify each step on the server.

## 1. Server packages
```bash
sudo apt update && sudo apt install -y python3-venv python3-dev nginx postgresql libpq-dev certbot python3-certbot-nginx
sudo adduser --system --group --home /srv/ngtraders ngtraders
```

## 2. Database
```bash
sudo -u postgres psql -c "CREATE USER ngtraders WITH PASSWORD 'CHOOSE-A-STRONG-PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE ngtraders OWNER ngtraders ENCODING 'UTF8';"
```

## 3. Application
```bash
sudo -u ngtraders -H bash
cd /srv/ngtraders
# copy the project here as /srv/ngtraders/app
python3 -m venv venv && source venv/bin/activate
pip install -r app/requirements.txt
```
Create `/etc/ngtraders.env` from `.env.example` (owner `root`, `chmod 640`, group `ngtraders`).
Generate the secret key: `python3 -c "import secrets;print(secrets.token_urlsafe(60))"`.

```bash
cd /srv/ngtraders/app
set -a; . /etc/ngtraders.env; set +a
python manage.py migrate
python manage.py setup_roles
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py check --deploy
```
`check --deploy` may still print two optional HSTS notes (include-subdomains, preload). They are deliberately
left off; enable them only once you are sure every subdomain will always use HTTPS.

## 4. Gunicorn + Nginx + HTTPS
```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/ngtraders.service
sudo systemctl daemon-reload && sudo systemctl enable --now ngtraders
sudo cp deploy/nginx.conf /etc/nginx/sites-available/ngtraders   # edit the domain name first
sudo ln -s /etc/nginx/sites-available/ngtraders /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com     # adds HTTPS + redirect
```
Static files are served by Nginx from `staticfiles/`; uploaded images from `media/`.
HTTPS is **required** for the microphone to work on phones.

## 5. Backups and recovery
```bash
sudo mkdir -p /var/backups/ngtraders && sudo chown ngtraders /var/backups/ngtraders
chmod +x /srv/ngtraders/app/deploy/backup.sh
sudo -u ngtraders crontab -e      # add:  30 2 * * * /srv/ngtraders/app/deploy/backup.sh
```
* Copy `/var/backups/ngtraders` **off the server** regularly (a backup on the same disk is not enough).
* **Test a restore** once: `createdb ngtraders_test && pg_restore -d ngtraders_test /var/backups/ngtraders/db-XXXX.dump`
* Restore for real: stop the service, `pg_restore --clean --if-exists -d ngtraders FILE.dump`, start the service.
* **Always take a manual backup before importing products or upgrading.**

## 6. Updating the site
```bash
sudo systemctl stop ngtraders ; backup ; git pull / copy new files
pip install -r requirements.txt ; python manage.py migrate ; python manage.py collectstatic --noinput
sudo systemctl start ngtraders
```

## 7. Notes
* Rate limiting counts per Gunicorn worker (3 workers ⇒ roughly 3× the stated limit). That is enough as basic
  abuse control; use Redis as the Django cache later if you need strict limits.
* Set `DJANGO_TRUST_XFF=1` only behind the provided Nginx config (it overwrites `X-Forwarded-For`).
* Logs: `journalctl -u ngtraders`. Customer phone numbers, passwords and speech text are not written to logs.
* Voice audio is never sent to or stored by this server. The browser's speech service (e.g. Google in Chrome) processes it.

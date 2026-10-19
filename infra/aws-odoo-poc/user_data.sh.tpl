#!/bin/bash
set -euo pipefail

dnf install -y docker
systemctl enable --now docker
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

mkdir -p /opt/odoo
cat > /opt/odoo/odoo-boot.sh <<'BOOT'
${odoo_boot_sh}
BOOT
chmod 755 /opt/odoo/odoo-boot.sh

# Mirrors the odoo + odoo-db services in the repo's docker-compose.yml.
cat > /opt/odoo/docker-compose.yml <<'COMPOSE'
services:
  odoo-db:
    image: postgres:15
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: odoo
      POSTGRES_PASSWORD: odoo
    volumes:
      - odoo-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U odoo"]
      interval: 5s
      timeout: 3s
      retries: 10

  odoo:
    image: odoo:17
    depends_on:
      odoo-db:
        condition: service_healthy
    environment:
      HOST: odoo-db
      USER: odoo
      PASSWORD: odoo
    ports:
      - "8069:8069"
    entrypoint: ["/bin/bash", "/odoo-boot.sh"]
    volumes:
      - odoo-web:/var/lib/odoo
      - /opt/odoo/odoo-boot.sh:/odoo-boot.sh:ro

volumes:
  odoo-db-data:
  odoo-web:
COMPOSE

cd /opt/odoo && docker-compose up -d

# nginx on 443 with a self-signed cert, proxying to Odoo on localhost:8069. Odoo
# itself only speaks plain HTTP; some corporate firewalls block plain-HTTP traffic
# to cloud IPs by app-id while allowing HTTPS to the same destination.
dnf install -y nginx
mkdir -p /etc/nginx/ssl
TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
# SAN must match the public IP exactly, or default (verified) TLS clients -- including
# this repo's OdooAdapter, which uses urllib with no verify=False override -- reject it.
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/odoo.key -out /etc/nginx/ssl/odoo.crt \
  -subj "/CN=$PUBLIC_IP" -addext "subjectAltName=IP:$PUBLIC_IP"

cat > /etc/nginx/conf.d/odoo.conf <<'NGINX'
server {
    listen 443 ssl;
    ssl_certificate     /etc/nginx/ssl/odoo.crt;
    ssl_certificate_key /etc/nginx/ssl/odoo.key;

    location / {
        proxy_pass http://127.0.0.1:8069;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 300s;
    }
}
NGINX

systemctl enable --now nginx

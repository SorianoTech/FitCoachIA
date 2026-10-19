#!/bin/bash
# cloud-init user-data para la EC2 de FitCoachIA (Ubuntu 24.04 LTS, x86_64).
# Deja el host como el servidor actual: Docker + Compose, usuario de despliegue con
# la regla sudoers de deploy.yml, /etc/fitcoachia y las redes Docker externas.
# Ver docs/despliegue-aws-ec2.md. Salida en /var/log/cloud-init-output.log.
set -euxo pipefail

# --- Editar antes de lanzar la instancia ---------------------------------------
DEPLOY_USER="fitcoach"
# Clave publica cuya privada esta en el secreto SERVER_PKEY de GitHub Actions.
DEPLOY_SSH_PUBKEY="ssh-ed25519 AAAA... github-actions-deploy"
SWAP_SIZE="2G"
# -------------------------------------------------------------------------------

export DEBIAN_FRONTEND=noninteractive

# Docker Engine >= 25 (start_interval de los healthchecks) y plugin Compose,
# desde el repositorio oficial de Docker.
apt-get update
apt-get install -y ca-certificates curl git make
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck source=/dev/null
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Rotacion de logs: sin ella, json-file crece sin limite y llena el disco.
cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
systemctl enable docker
systemctl restart docker

# AWS CLI para subir backups a S3 con el rol de la instancia.
snap install aws-cli --classic

# Swap como colchon ante picos de memoria del embedder.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l "$SWAP_SIZE" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Usuario de despliegue: docker sin sudo (deploy.yml hace pull/inspect/rm) y sudo
# sin contrasena solo para lo que necesita leer el .env.prod de root.
id "$DEPLOY_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
echo "$DEPLOY_SSH_PUBKEY" > "/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
echo "$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/make, /usr/bin/test, /bin/ls" > /etc/sudoers.d/fitcoach-deploy
chmod 0440 /etc/sudoers.d/fitcoach-deploy
visudo -c

# Ficheros de entorno fuera del repositorio, solo legibles por root.
install -d -m 700 -o root -g root /etc/fitcoachia/prod /etc/fitcoachia/dev

# Redes externas que esperan los Compose (make prod-up tambien las crea).
for network in proxy-network fitcoach-prod-internal; do
  docker network inspect "$network" >/dev/null 2>&1 || docker network create "$network"
done

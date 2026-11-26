#!/bin/sh
# Déclare l'UID courant dans /etc/passwd (conteneur uniquement) puis exécute la commande.
if ! getent passwd "$(id -u)" >/dev/null 2>&1; then
  echo "atelier:x:$(id -u):$(id -g):atelier:${HOME:-/tmp}:/bin/sh" >> /etc/passwd
fi
exec "$@"

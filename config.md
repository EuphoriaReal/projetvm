# Configuration Réseau Multi-VM

## Architecture Réseau

```
Proxmox Bridge (vmbr0) - 192.168.1.0/24
│
├── VM Linux 1 (sans GUI) - 192.168.1.10
│   └── Docker Network 172.20.0.0/24
│       ├── Registry: 172.20.0.2:5001
│       ├── Player1: 172.20.0.11
│       └── Player3: 172.20.0.13
│
├── VM Linux 2 (avec GUI) - 192.168.1.11
│   └── Docker Network 172.21.0.0/24
│       ├── Server: 172.21.0.10:5000
│       ├── Player2: 172.21.0.12
│       └── Dashboard: 172.21.0.20:3000
│
└── VM Windows - 192.168.1.12
    └── Player4 (natif ou container Docker Desktop)
```

## Configuration sur chaque VM

### VM Linux 1 (Registry + Players)

```bash
# 1. Configurer le registry comme insecure
sudo nano /etc/docker/daemon.json
```

```json
{
  "insecure-registries": ["192.168.1.10:5001"]
}
```

```bash
# 2. Redémarrer Docker
sudo systemctl restart docker

# 3. Builder et pousser les images
cd ~/bomb-game
docker build -t bomb-server:latest ./server
docker build -t bomb-player:latest ./player

docker tag bomb-server:latest 192.168.1.10:5001/bomb-server:latest
docker tag bomb-player:latest 192.168.1.10:5001/bomb-player:latest

docker push 192.168.1.10:5001/bomb-server:latest
docker push 192.168.1.10:5001/bomb-player:latest

# 4. Lancer les services
docker-compose -f docker-compose-vm1.yml up -d
```

### VM Linux 2 (Server + Dashboard)

```bash
# 1. Configurer le registry
sudo nano /etc/docker/daemon.json
```

```json
{
  "insecure-registries": ["192.168.1.10:5001"]
}
```

```bash
# 2. Redémarrer Docker
sudo systemctl restart docker

# 3. Tester la connexion au registry
curl http://192.168.1.10:5001/v2/_catalog

# 4. Pull les images depuis le registry
docker pull 192.168.1.10:5001/bomb-server:latest
docker pull 192.168.1.10:5001/bomb-player:latest

# 5. Lancer les services
docker-compose -f docker-compose-vm2.yml up -d
```

### VM Windows (Bonus - Player4)

#### Option A : Docker Desktop

```powershell
# 1. Installer Docker Desktop
# Télécharger depuis https://www.docker.com/products/docker-desktop

# 2. Configurer le registry insecure
# Docker Desktop > Settings > Docker Engine
# Ajouter dans le JSON:
{
  "insecure-registries": ["192.168.1.10:5001"]
}

# 3. Pull et run
docker pull 192.168.1.10:5001/bomb-player:latest

docker run -d `
  --name bomb_player4 `
  -e PLAYER_NAME=YellowSamurai `
  -e SERVER_HOST=192.168.1.11 `
  -e SERVER_PORT=5000 `
  -e REACTION_TIME=2.0 `
  192.168.1.10:5001/bomb-player:latest
```

#### Option B : Python natif (plus simple pour le bonus)

```powershell
# 1. Installer Python 3.11+
# Télécharger depuis https://www.python.org

# 2. Copier player.py sur Windows

# 3. Configurer les variables d'environnement
$env:PLAYER_NAME="YellowSamurai"
$env:SERVER_HOST="192.168.1.11"
$env:SERVER_PORT="5000"
$env:REACTION_TIME="2.0"

# 4. Lancer le joueur
python player.py
```

## Configuration Firewall

### Sur toutes les VMs Linux

```bash
# Autoriser les ports nécessaires
sudo ufw allow 5000/tcp  # Port serveur de jeu
sudo ufw allow 5001/tcp  # Port registry (VM1 uniquement)
sudo ufw allow 3000/tcp  # Port dashboard (VM2 uniquement)
sudo ufw allow 8080/tcp  # Port API dashboard (VM2 uniquement)

# Ou désactiver temporairement pour les tests
sudo ufw disable
```

### Sur Windows

```powershell
# Autoriser les connexions sortantes vers le serveur
# Normalement déjà autorisé par défaut
```

## Tests de connectivité

### Depuis VM2, tester la connexion au registry (VM1)

```bash
# Test HTTP
curl http://192.168.1.10:5001/v2/_catalog

# Test ping
ping 192.168.1.10

# Test port
nc -zv 192.168.1.10 5001
```

### Depuis VM1, tester la connexion au serveur (VM2)

```bash
# Test ping
ping 192.168.1.11

# Test port du serveur
nc -zv 192.168.1.11 5000
```

### Depuis Windows, tester la connexion au serveur (VM2)

```powershell
# Test ping
ping 192.168.1.11

# Test port
Test-NetConnection -ComputerName 192.168.1.11 -Port 5000
```

## Démarrage complet du système

1. **VM1** : `docker-compose -f docker-compose-vm1.yml up -d`
2. **VM2** : `docker-compose -f docker-compose-vm2.yml up -d`
3. **Windows** : `docker run ...` ou `python player.py`

## Monitoring

```bash
# Voir les logs du serveur (VM2)
docker logs -f bomb_server

# Voir les logs de tous les joueurs
docker logs -f bomb_player1  # VM1
docker logs -f bomb_player2  # VM2
docker logs -f bomb_player3  # VM1
docker logs -f bomb_player4  # Windows

# Voir l'état du registry (VM1)
curl http://192.168.1.10:5001/v2/_catalog
```

## Dépannage

### Erreur "connection refused"

* Vérifier que le serveur est bien lancé
* Vérifier les règles firewall
* Vérifier les adresses IP

### Erreur "manifest unknown" au push

* Vérifier que le registry est bien lancé
* Vérifier la configuration insecure-registries

### Les joueurs ne se connectent pas

* Vérifier que SERVER_HOST pointe vers l'IP correcte
* Vérifier que le port 5000 est ouvert
* Vérifier les logs du serveur

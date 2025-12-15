# Guide de Déploiement - Bomb Game Multi-VM

## Prérequis

* 3 VMs dans Proxmox :
  * VM1 Linux sans GUI (Ubuntu/Debian)
  * VM2 Linux avec GUI (Ubuntu/Debian)
  * VM3 Windows
* Docker et Docker Compose installés sur les VMs Linux
* Réseau bridge configuré dans Proxmox

## Étape 1 : Préparation de l'infrastructure

### 1.1 Configuration réseau dans Proxmox

Assurez-vous que toutes les VMs sont sur le même bridge (vmbr0) et peuvent communiquer entre elles.

```bash
# Tester la connectivité depuis chaque VM
ping 192.168.1.10  # VM1
ping 192.168.1.11  # VM2
ping 192.168.1.12  # VM3 (Windows)
```

## Étape 2 : Setup sur VM1 (Registry + Players)

### 2.1 Créer la structure du projet

```bash
mkdir -p ~/bomb-game/{server,player,dashboard}
cd ~/bomb-game
```

### 2.2 Créer les fichiers

Créez les fichiers suivants avec le contenu fourni :

* `server/Dockerfile`
* `server/server.py`
* `player/Dockerfile`
* `player/player.py`
* `docker-compose-vm1.yml`

### 2.3 Configuration du registry

```bash
# Créer le fichier de configuration Docker
sudo mkdir -p /etc/docker
sudo nano /etc/docker/daemon.json
```

Ajouter :

```json
{
  "insecure-registries": ["192.168.1.10:5001"]
}
```

```bash
# Redémarrer Docker
sudo systemctl restart docker
```

### 2.4 Build et push des images

```bash
# Builder les images localement
docker build -t bomb-server:latest ./server
docker build -t bomb-player:latest ./player

# Lancer le registry
docker-compose -f docker-compose-vm1.yml up -d registry

# Attendre quelques secondes que le registry démarre
sleep 5

# Tagger et pusher les images
docker tag bomb-server:latest 192.168.1.10:5001/bomb-server:latest
docker tag bomb-player:latest 192.168.1.10:5001/bomb-player:latest

docker push 192.168.1.10:5001/bomb-server:latest
docker push 192.168.1.10:5001/bomb-player:latest

# Vérifier que les images sont dans le registry
curl http://192.168.1.10:5001/v2/_catalog
```

### 2.5 Lancer les joueurs sur VM1

```bash
# Lancer tous les services
docker-compose -f docker-compose-vm1.yml up -d

# Vérifier les logs
docker logs -f bomb_player1
```

## Étape 3 : Setup sur VM2 (Server + Dashboard)

### 3.1 Créer la structure

```bash
mkdir -p ~/bomb-game
cd ~/bomb-game
```

### 3.2 Créer les fichiers

Créez `docker-compose-vm2.yml` avec le contenu fourni.

### 3.3 Configuration du registry

```bash
sudo nano /etc/docker/daemon.json
```

Ajouter :

```json
{
  "insecure-registries": ["192.168.1.10:5001"]
}
```

```bash
sudo systemctl restart docker
```

### 3.4 Pull et lancement

```bash
# Tester la connexion au registry
curl http://192.168.1.10:5001/v2/_catalog

# Pull les images
docker pull 192.168.1.10:5001/bomb-server:latest
docker pull 192.168.1.10:5001/bomb-player:latest

# Lancer les services
docker-compose -f docker-compose-vm2.yml up -d

# Vérifier les logs du serveur
docker logs -f bomb_server
```

## Étape 4 : Setup sur Windows (Bonus)

### Option A : Avec Docker Desktop

1. **Installer Docker Desktop**

   * Télécharger depuis https://www.docker.com/products/docker-desktop
   * Installer et redémarrer
2. **Configurer le registry insecure**

   * Ouvrir Docker Desktop
   * Settings > Docker Engine
   * Ajouter dans le JSON :

   ```json
   {
     "insecure-registries": ["192.168.1.10:5001"]
   }
   ```

   * Apply & Restart
3. **Lancer le joueur**

   ```powershell
   docker pull 192.168.1.10:5001/bomb-player:latest

   docker run -d `
     --name bomb_player4 `
     -e PLAYER_NAME=YellowSamurai `
     -e SERVER_HOST=192.168.1.11 `
     -e SERVER_PORT=5000 `
     -e REACTION_TIME=2.0 `
     192.168.1.10:5001/bomb-player:latest

   docker logs -f bomb_player4
   ```

### Option B : Python natif (recommandé pour le bonus)

1. **Installer Python 3.11+**
   * Télécharger depuis https://www.python.org
   * Cocher "Add Python to PATH"
2. **Récupérer le code**
   * Copier `player.py` sur Windows
   * Ou cloner depuis un repo Git
3. **Lancer le joueur**
   ```powershell
   # Définir les variables d'environnement
   $env:PLAYER_NAME="YellowSamurai"
   $env:SERVER_HOST="192.168.1.11"
   $env:SERVER_PORT="5000"
   $env:REACTION_TIME="2.0"

   # Lancer
   python player.py
   ```

## Étape 5 : Vérification et Tests

### 5.1 Vérifier que tout fonctionne

```bash
# Sur VM1 - Voir les logs des joueurs
docker logs -f bomb_player1
docker logs -f bomb_player3

# Sur VM2 - Voir les logs du serveur
docker logs -f bomb_server

# Sur VM2 - Voir tous les containers actifs
docker ps
```

### 5.2 Accéder au dashboard

Depuis n'importe quel navigateur sur le réseau :

```
http://192.168.1.11:3000
```

### 5.3 Tests de communication

```bash
# Depuis n'importe quelle VM, tester le serveur
telnet 192.168.1.11 5000

# Tester le registry
curl http://192.168.1.10:5001/v2/_catalog
```

## Dépannage

### Les joueurs ne se connectent pas au serveur

```bash
# Vérifier que le serveur écoute
netstat -tlnp | grep 5000

# Vérifier les logs du serveur
docker logs bomb_server

# Vérifier les règles firewall
sudo ufw status
sudo ufw allow 5000/tcp

# Ou désactiver temporairement
sudo ufw disable
```

### Erreur "connection refused" depuis Windows

```powershell
# Tester la connectivité
ping 192.168.1.11
Test-NetConnection -ComputerName 192.168.1.11 -Port 5000

# Vérifier le firewall Windows
# Panneau de configuration > Pare-feu Windows > Paramètres avancés
# Autoriser les connexions sortantes sur le port 5000
```

### Le registry ne fonctionne pas

```bash
# Vérifier que le registry tourne
docker ps | grep registry

# Voir les logs du registry
docker logs bomb_registry

# Tester l'accès
curl http://192.168.1.10:5001/v2/_catalog

# Reconstruire si nécessaire
docker-compose -f docker-compose-vm1.yml down
docker-compose -f docker-compose-vm1.yml up -d registry
```

### Les containers ne trouvent pas les images

```bash
# Sur VM2, vérifier la configuration du registry
cat /etc/docker/daemon.json

# Redémarrer Docker
sudo systemctl restart docker

# Re-pull les images
docker pull 192.168.1.10:5001/bomb-server:latest
```

## Commandes utiles

```bash
# Voir tous les containers en cours
docker ps -a

# Voir les logs en temps réel
docker logs -f <container_name>

# Redémarrer un container
docker restart <container_name>

# Arrêter tous les services
docker-compose down

# Relancer tous les services
docker-compose up -d

# Voir l'utilisation des ressources
docker stats

# Nettoyer les images inutilisées
docker system prune -a
```

## Checklist finale

* [ ] VM1 : Registry opérationnel (port 5001)
* [ ] VM1 : Player1 et Player3 connectés au serveur
* [ ] VM2 : Serveur opérationnel (port 5000)
* [ ] VM2 : Player2 connecté au serveur
* [ ] VM2 : Dashboard accessible (port 3000)
* [ ] Windows : Player4 connecté au serveur (BONUS)
* [ ] Tous les joueurs peuvent communiquer
* [ ] Le jeu démarre automatiquement avec 2+ joueurs
* [ ] Les bombes explosent et éliminent les joueurs
* [ ] Un gagnant est déclaré à la fin

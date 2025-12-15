import socket
import json
import threading
import time
import random
import os

class BombGameServer:
    def __init__(self):
        self.host = '0.0.0.0'
        self.port = int(os.getenv('SERVER_PORT', 5000))
        
        # Gestion des joueurs
        self.players = {}  # {socket: {id, name, alive, address}}
        self.alive_players_sockets = [] # Liste ordonnée des sockets des joueurs vivants
        
        # État du jeu
        self.current_holder = None # Socket du porteur
        self.bomb_timer = 0
        self.game_started = False
        
        # Configuration
        self.min_timer = int(os.getenv('MIN_TIMER', 5))
        self.max_timer = int(os.getenv('MAX_TIMER', 15))
        self.min_players = int(os.getenv('MIN_PLAYERS', 2))
        
        # Thread safety
        self.lock = threading.Lock()
        self.running = True

    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server_socket.bind((self.host, self.port))
            server_socket.listen(10)
            print(f"Serveur demarre sur {self.host}:{self.port}")
            print(f"En attente de {self.min_players} joueurs minimum...")
            
            # Lancer le timer de la bombe en arrière-plan
            threading.Thread(target=self.bomb_timer_loop, daemon=True).start()
            
            while self.running:
                client_socket, address = server_socket.accept()
                print(f"Connexion entrante: {address}")
                
                # Gérer chaque client dans un thread séparé
                threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, address),
                    daemon=True
                ).start()
                
        except Exception as e:
            print(f"Erreur critique du serveur: {e}")
        finally:
            server_socket.close()

    def handle_client(self, client_socket, address):
        buffer = ""
        try:
            while True:
                data = client_socket.recv(4096).decode('utf-8')
                if not data:
                    break # Déconnexion propre
                
                buffer += data
                
                # Traitement du flux TCP (gestion des messages collés ou coupés)
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            message = json.loads(line)
                            self.process_message(client_socket, message, address)
                        except json.JSONDecodeError:
                            print(f"Erreur de decodage JSON venant de {address}")

        except ConnectionResetError:
            print(f"Connexion reinitialisee par {address}")
        except Exception as e:
            print(f"Erreur avec le client {address}: {e}")
        finally:
            self.disconnect_player(client_socket)

    def process_message(self, client_socket, message, address):
        msg_type = message.get('type')
        
        if msg_type == 'JOIN':
            self.handle_join(client_socket, message, address)
        elif msg_type == 'PASS_BOMB':
            self.handle_pass_bomb(client_socket, message)

    def handle_join(self, client_socket, message, address):
        player_id = message['player_id']
        player_name = message['player_name']
        
        with self.lock:
            self.players[client_socket] = {
                'id': player_id,
                'name': player_name,
                'address': address,
                'alive': True
            }
            if client_socket not in self.alive_players_sockets:
                self.alive_players_sockets.append(client_socket)
        
        print(f"JOIN: {player_name} ({player_id})")
        self.broadcast_game_state()
        
        # Vérifier si on peut lancer la partie
        with self.lock:
            if not self.game_started and len(self.alive_players_sockets) >= self.min_players:
                self.start_new_round()

    def handle_pass_bomb(self, sender_socket, message):
        target_id = message.get('to')
        
        with self.lock:
            # Sécurités
            if not self.game_started:
                return
            if sender_socket != self.current_holder:
                return # Anti-triche: seul le porteur peut passer la bombe
            
            # Trouver le socket de la cible
            target_socket = None
            for sock, info in self.players.items():
                if info['id'] == target_id and info['alive']:
                    target_socket = sock
                    break
            
            if target_socket:
                self.current_holder = target_socket
                sender_name = self.players[sender_socket]['name']
                target_name = self.players[target_socket]['name']
                
                print(f"PASS: {sender_name} -> {target_name} ({self.bomb_timer:.1f}s)")
                
                self.send_bomb_update(target_socket, sender_name)
                self.broadcast_game_state()

    def start_new_round(self):
        # Cette méthode doit être appelée sous un lock
        if len(self.alive_players_sockets) < 2:
            return

        print("\n--- DEBUT DU ROUND ---")
        self.game_started = True
        self.current_holder = random.choice(self.alive_players_sockets)
        self.bomb_timer = random.uniform(self.min_timer, self.max_timer)
        
        holder_name = self.players[self.current_holder]['name']
        print(f"La bombe est donnee a {holder_name} (Timer: {self.bomb_timer:.1f}s)")
        
        self.send_bomb_update(self.current_holder, "SERVER")
        self.broadcast_game_state()

    def bomb_timer_loop(self):
        """Boucle principale qui gère le décompte et les explosions"""
        while self.running:
            time.sleep(0.1)
            
            with self.lock:
                if self.game_started and self.current_holder:
                    self.bomb_timer -= 0.1
                    
                    if self.bomb_timer <= 0:
                        self.handle_explosion()

    def handle_explosion(self):
        # Cette méthode est appelée sous lock par bomb_timer_loop
        victim_socket = self.current_holder
        if not victim_socket or victim_socket not in self.players:
            return

        victim_name = self.players[victim_socket]['name']
        print(f"\nBOOOM ! {victim_name} a explose !\n")
        
        # Mise à jour état
        self.players[victim_socket]['alive'] = False
        if victim_socket in self.alive_players_sockets:
            self.alive_players_sockets.remove(victim_socket)
        
        self.current_holder = None
        self.game_started = False # Pause temporaire
        
        # Notifier tout le monde
        survivor_names = [self.players[s]['name'] for s in self.alive_players_sockets]
        self.broadcast({
            'type': 'EXPLODE',
            'victim': victim_name,
            'survivors': survivor_names
        })
        
        # Vérification victoire
        if len(self.alive_players_sockets) == 1:
            winner_socket = self.alive_players_sockets[0]
            winner_name = self.players[winner_socket]['name']
            print(f"VICTOIRE: {winner_name} remporte la partie !")
            
            self.broadcast({
                'type': 'WINNER',
                'winner': winner_name
            })
            # Reset complet (on garde les connexions mais on reset les status)
            threading.Timer(5.0, self.reset_game).start()
            
        elif len(self.alive_players_sockets) > 1:
            # On continue la partie après une courte pause
            threading.Timer(3.0, self.next_turn_after_explosion).start()
        else:
            print("Match nul (tout le monde est mort)")
            threading.Timer(5.0, self.reset_game).start()

    def next_turn_after_explosion(self):
        with self.lock:
            # Vérifier qu'il reste assez de joueurs (quelqu'un a pu se déconnecter entre temps)
            if len(self.alive_players_sockets) >= 2:
                self.start_new_round()
            else:
                self.reset_game()

    def reset_game(self):
        with self.lock:
            print("Reinitialisation de la partie...")
            self.game_started = False
            self.current_holder = None
            
            # Ressusciter tout le monde présent
            self.alive_players_sockets = []
            for sock, info in self.players.items():
                info['alive'] = True
                self.alive_players_sockets.append(sock)
            
            if len(self.alive_players_sockets) >= self.min_players:
                self.start_new_round()

    def send_bomb_update(self, target_socket, from_name):
        available = [
            self.players[s]['id'] 
            for s in self.alive_players_sockets 
            if s != target_socket
        ]
        
        msg = {
            'type': 'RECEIVE_BOMB',
            'timer': round(self.bomb_timer, 2),
            'from': from_name,
            'available_targets': available
        }
        self.send_to_socket(target_socket, msg)

    def broadcast_game_state(self):
        # Création de la liste des joueurs pour l'affichage client
        players_list = []
        for s, info in self.players.items():
            players_list.append({'name': info['name'], 'alive': info['alive']})
            
        holder_name = None
        if self.current_holder and self.current_holder in self.players:
            holder_name = self.players[self.current_holder]['name']

        state_msg = {
            'type': 'GAME_STATE',
            'players': players_list,
            'current_holder': holder_name,
            'timer': round(self.bomb_timer, 1) if self.game_started else 0
        }
        self.broadcast(state_msg)

    def broadcast(self, message):
        for sock in list(self.players.keys()):
            self.send_to_socket(sock, message)

    def send_to_socket(self, sock, message):
        try:
            data = json.dumps(message) + '\n'
            sock.sendall(data.encode('utf-8'))
        except Exception:
            # Si l'envoi échoue, on assume que le joueur est déconnecté
            # Le thread handle_client s'occupera du nettoyage
            pass

    def disconnect_player(self, sock):
        with self.lock:
            if sock in self.players:
                name = self.players[sock]['name']
                print(f"Deconnexion: {name}")
                
                # Si le joueur avait la bombe, il faut la donner à quelqu'un d'autre
                was_holder = (sock == self.current_holder)
                
                del self.players[sock]
                if sock in self.alive_players_sockets:
                    self.alive_players_sockets.remove(sock)
                
                if self.game_started:
                    if len(self.alive_players_sockets) < 2:
                        # Pas assez de joueurs pour continuer
                        self.game_started = False
                        print("Partie interrompue : pas assez de joueurs.")
                        self.broadcast({'type': 'WINNER', 'winner': 'PERSONNE (Arrêt jeu)'})
                        threading.Timer(3.0, self.reset_game).start()
                    elif was_holder:
                        # Le porteur a rage-quit, on donne la bombe à un autre
                        print(f"Le porteur {name} s'est deconnecte. Transfert de la bombe...")
                        self.start_new_round()
                    else:
                        self.broadcast_game_state()
                
            try:
                sock.close()
            except:
                pass

if __name__ == '__main__':
    server = BombGameServer()
    server.start()
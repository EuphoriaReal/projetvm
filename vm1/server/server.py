import socket
import json
import threading
import time
import random
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

class BombGameServer:
    def __init__(self):
        self.host = '0.0.0.0'
        self.port = int(os.getenv('SERVER_PORT', 5000))
        self.api_port = int(os.getenv('API_PORT', 8080))
        self.players = {}  # {connection: player_info}
        self.alive_players = []
        self.current_holder = None
        self.bomb_timer = 0
        self.min_timer = int(os.getenv('MIN_TIMER', 3))
        self.max_timer = int(os.getenv('MAX_TIMER', 10))
        self.min_players = int(os.getenv('MIN_PLAYERS', 2))
        self.game_started = False
        self.lock = threading.Lock()
        self.events = []  # Historique des événements
        self.max_events = 50
        
    def add_event(self, event_type, message):
        """Ajouter un événement à l'historique"""
        with self.lock:
            self.events.insert(0, {
                'type': event_type,
                'message': message,
                'timestamp': time.time()
            })
            if len(self.events) > self.max_events:
                self.events.pop()
    
    def get_game_state(self):
        """Retourner l'état actuel du jeu (pour l'API)"""
        with self.lock:
            return {
                'game_started': self.game_started,
                'players': [
                    {
                        'name': info['name'],
                        'id': info['id'],
                        'alive': info['alive'],
                        'has_bomb': sock == self.current_holder
                    }
                    for sock, info in self.players.items()
                ],
                'current_holder': self.players[self.current_holder]['name'] if self.current_holder else None,
                'timer': round(self.bomb_timer, 1) if self.game_started else 0,
                'events': self.events[:10]  # Les 10 derniers événements
            }
    
    def start(self):
        # Démarrer le serveur API HTTP dans un thread séparé
        api_thread = threading.Thread(target=self.start_api_server, daemon=True)
        api_thread.start()
        
        # Démarrer le serveur de jeu principal
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(10)
        
        print(f"Serveur de jeu démarré sur {self.host}:{self.port}")
        print(f"API HTTP démarrée sur {self.host}:{self.api_port}")
        print(f"En attente de {self.min_players} joueurs minimum...")
        
        self.add_event('info', f'Serveur démarré - En attente de {self.min_players} joueurs')
        
        # Thread pour gérer le timer de la bombe
        timer_thread = threading.Thread(target=self.bomb_timer_thread, daemon=True)
        timer_thread.start()
        
        while True:
            try:
                client_socket, address = server_socket.accept()
                print(f"Nouvelle connexion: {address}")
                
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, address),
                    daemon=True
                )
                client_thread.start()
                
            except Exception as e:
                print(f"Erreur serveur: {e}")
    
    def start_api_server(self):
        """Démarrer le serveur HTTP pour l'API"""
        game_server = self
        
        class APIHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/api/state':
                    # Retourner l'état du jeu en JSON
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                    self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                    self.end_headers()
                    
                    state = game_server.get_game_state()
                    self.wfile.write(json.dumps(state).encode())
                elif self.path == '/health':
                    # Endpoint de santé
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({'status': 'ok'}).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def do_OPTIONS(self):
                # Gérer les requêtes OPTIONS pour CORS
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
            
            def log_message(self, format, *args):
                # Désactiver les logs HTTP pour ne pas polluer la console
                pass
        
        api_server = HTTPServer(('0.0.0.0', self.api_port), APIHandler)
        print(f"Serveur API prêt sur le port {self.api_port}")
        api_server.serve_forever()
    
    def handle_client(self, client_socket, address):
        try:
            # Recevoir le message de JOIN
            data = client_socket.recv(4096).decode('utf-8')
            if not data:
                return
            
            message = json.loads(data)
            
            if message['type'] == 'JOIN':
                player_id = message['player_id']
                player_name = message['player_name']
                
                with self.lock:
                    self.players[client_socket] = {
                        'id': player_id,
                        'name': player_name,
                        'address': address,
                        'alive': True
                    }
                    self.alive_players.append(client_socket)
                
                print(f"{player_name} ({player_id}) a rejoint la partie")
                self.add_event('join', f"{player_name} a rejoint la partie")
                self.broadcast_game_state()
                
                # Démarrer la partie si assez de joueurs
                if len(self.alive_players) >= self.min_players and not self.game_started:
                    self.start_game()
                
                # Boucle pour recevoir les messages du joueur
                while True:
                    data = client_socket.recv(4096).decode('utf-8')
                    if not data:
                        break
                    
                    msg = json.loads(data)
                    self.handle_message(client_socket, msg)
                    
        except Exception as e:
            print(f"Erreur client {address}: {e}")
        finally:
            self.remove_player(client_socket)
            client_socket.close()
    
    def handle_message(self, sender_socket, message):
        msg_type = message['type']
        
        if msg_type == 'PASS_BOMB':
            target_id = message['to']
            self.pass_bomb(sender_socket, target_id)
    
    def start_game(self):
        with self.lock:
            if self.game_started:
                return
            
            self.game_started = True
            print("\n=== DÉBUT DE LA PARTIE ===\n")
            self.add_event('game_start', 'DÉBUT DE LA PARTIE !')
            
            # Donner la bombe au premier joueur
            self.current_holder = random.choice(self.alive_players)
            self.bomb_timer = random.uniform(self.min_timer, self.max_timer)
            
            holder_info = self.players[self.current_holder]
            print(f"{holder_info['name']} a reçu la bombe ! (timer: {self.bomb_timer:.1f}s)")
            self.add_event('bomb_received', f"{holder_info['name']} a reçu la bombe ! (timer: {self.bomb_timer:.1f}s)")
            
            self.send_to_player(self.current_holder, {
                'type': 'RECEIVE_BOMB',
                'timer': self.bomb_timer,
                'available_targets': self.get_available_targets(self.current_holder)
            })
            
            self.broadcast_game_state()
    
    def pass_bomb(self, from_socket, target_id):
        with self.lock:
            if from_socket != self.current_holder:
                return  # Seul le porteur peut passer la bombe
            
            # Trouver le socket du joueur cible
            target_socket = None
            for sock, info in self.players.items():
                if info['id'] == target_id and info['alive']:
                    target_socket = sock
                    break
            
            if not target_socket:
                return
            
            from_info = self.players[from_socket]
            to_info = self.players[target_socket]
            
            print(f"{from_info['name']} passe la bombe à {to_info['name']} (timer: {self.bomb_timer:.1f}s)")
            self.add_event('bomb_passed', f"{from_info['name']} → {to_info['name']} (timer: {self.bomb_timer:.1f}s)")
            
            self.current_holder = target_socket
            
            self.send_to_player(target_socket, {
                'type': 'RECEIVE_BOMB',
                'timer': self.bomb_timer,
                'from': from_info['name'],
                'available_targets': self.get_available_targets(target_socket)
            })
            
            self.broadcast_game_state()
    
    def bomb_timer_thread(self):
        while True:
            time.sleep(0.1)
            
            with self.lock:
                if self.game_started and self.current_holder:
                    self.bomb_timer -= 0.1
                    
                    if self.bomb_timer <= 0:
                        self.explode_bomb()
    
    def explode_bomb(self):
        if not self.current_holder:
            return
        
        victim_info = self.players[self.current_holder]
        print(f"\nBOOOM ! {victim_info['name']} a explosé !\n")
        self.add_event('explosion', f"BOOOM ! {victim_info['name']} a explosé !")
        
        # Marquer le joueur comme mort
        victim_info['alive'] = False
        self.alive_players.remove(self.current_holder)
        
        # Notifier tous les joueurs
        self.broadcast({
            'type': 'EXPLODE',
            'victim': victim_info['name'],
            'survivors': [self.players[s]['name'] for s in self.alive_players]
        })
        
        # Vérifier s'il y a un gagnant
        if len(self.alive_players) == 1:
            winner_info = self.players[self.alive_players[0]]
            print(f"\n{winner_info['name']} a gagné la partie ! 🏆\n")
            self.add_event('winner', f"{winner_info['name']} a gagné la partie !")
            
            self.broadcast({
                'type': 'WINNER',
                'winner': winner_info['name']
            })
            
            self.reset_game()
        elif len(self.alive_players) > 0:
            # Continuer avec un nouveau porteur
            self.current_holder = random.choice(self.alive_players)
            self.bomb_timer = random.uniform(self.min_timer, self.max_timer)
            
            holder_info = self.players[self.current_holder]
            print(f"{holder_info['name']} a maintenant la bombe ! (timer: {self.bomb_timer:.1f}s)")
            self.add_event('bomb_received', f"{holder_info['name']} a maintenant la bombe ! (timer: {self.bomb_timer:.1f}s)")
            
            self.send_to_player(self.current_holder, {
                'type': 'RECEIVE_BOMB',
                'timer': self.bomb_timer,
                'available_targets': self.get_available_targets(self.current_holder)
            })
            
            self.broadcast_game_state()
    
    def get_available_targets(self, current_socket):
        targets = []
        for sock, info in self.players.items():
            if sock != current_socket and info['alive']:
                targets.append(info['id'])
        return targets
    
    def broadcast_game_state(self):
        state = {
            'type': 'GAME_STATE',
            'players': [{'name': info['name'], 'alive': info['alive']} 
                       for info in self.players.values()],
            'current_holder': self.players[self.current_holder]['name'] if self.current_holder else None,
            'timer': round(self.bomb_timer, 1) if self.game_started else 0
        }
        self.broadcast(state)
    
    def broadcast(self, message):
        dead_sockets = []
        for sock in list(self.players.keys()):
            try:
                self.send_to_player(sock, message)
            except:
                dead_sockets.append(sock)
        
        for sock in dead_sockets:
            self.remove_player(sock)
    
    def send_to_player(self, sock, message):
        try:
            sock.sendall((json.dumps(message) + '\n').encode('utf-8'))
        except:
            pass
    
    def remove_player(self, sock):
        with self.lock:
            if sock in self.players:
                player_info = self.players[sock]
                print(f"{player_info['name']} a quitté la partie")
                self.add_event('leave', f"{player_info['name']} a quitté la partie")
                
                if sock in self.alive_players:
                    self.alive_players.remove(sock)
                
                if sock == self.current_holder:
                    self.current_holder = None
                    if len(self.alive_players) > 0:
                        self.current_holder = random.choice(self.alive_players)
                        self.bomb_timer = random.uniform(self.min_timer, self.max_timer)
                
                del self.players[sock]
    
    def reset_game(self):
        time.sleep(5)  # Pause avant de recommencer
        with self.lock:
            self.game_started = False
            self.current_holder = None
            self.bomb_timer = 0
            
            # Réinitialiser tous les joueurs
            for info in self.players.values():
                info['alive'] = True
            
            self.alive_players = list(self.players.keys())
            
            if len(self.alive_players) >= self.min_players:
                print("\nNouvelle partie !\n")
                self.add_event('game_start', 'Nouvelle partie !')
                self.start_game()

if __name__ == '__main__':
    server = BombGameServer()
    server.start()
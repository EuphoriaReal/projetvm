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
        self.events = []
        self.max_events = 50

    def add_event(self, event_type, message):
        """Historique des événements pour l'API"""
        with self.lock:
            self.events.insert(0, {
                'type': event_type,
                'message': message,
                'timestamp': time.time()
            })
            if len(self.events) > self.max_events:
                self.events.pop()

    def get_game_state(self):
        """État actuel pour l'API HTTP"""
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
                'events': self.events[:10]
            }

    def start(self):
        # API HTTP
        api_thread = threading.Thread(target=self.start_api_server, daemon=True)
        api_thread.start()

        # Socket Jeu
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(10)

        print(f"[INFO] Serveur de jeu: {self.host}:{self.port}")
        print(f"[INFO] API HTTP: {self.host}:{self.api_port}")
        self.add_event('system', f'Serveur demarre - Attente de {self.min_players} joueurs')

        threading.Thread(target=self.bomb_timer_thread, daemon=True).start()

        while True:
            try:
                client_socket, address = server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client_socket, address), daemon=True).start()
            except Exception as e:
                print(f"[ERREUR] Serveur socket: {e}")

    def start_api_server(self):
        game_server = self
        class APIHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/api/state':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(game_server.get_game_state()).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            def log_message(self, format, *args): pass

        api_server = HTTPServer(('0.0.0.0', self.api_port), APIHandler)
        api_server.serve_forever()

    def handle_client(self, client_socket, address):
        player_name = "Inconnu"
        try:
            # Utilisation de makefile pour lire ligne par ligne (plus fiable que recv direct)
            f = client_socket.makefile('r', encoding='utf-8')
            line = f.readline()
            if not line: return
            
            message = json.loads(line)
            if message.get('type') == 'JOIN':
                p_id = message['player_id']
                player_name = message['player_name']

                with self.lock:
                    self.players[client_socket] = {'id': p_id, 'name': player_name, 'alive': True}
                    self.alive_players.append(client_socket)

                print(f"[JOIN] {player_name} a rejoint")
                self.add_event('join', f"{player_name} a rejoint la partie")
                self.broadcast_game_state()

                if len(self.alive_players) >= self.min_players and not self.game_started:
                    self.start_game()

                # Boucle de messages
                for line in f:
                    msg = json.loads(line)
                    self.handle_message(client_socket, msg)
        except Exception as e:
            print(f"[INFO] Deconnexion {player_name} ({address}): {e}")
        finally:
            self.remove_player(client_socket)
            client_socket.close()

    def handle_message(self, sender_socket, message):
        if message.get('type') == 'PASS_BOMB':
            self.pass_bomb(sender_socket, message.get('to'))

    def start_game(self):
        with self.lock:
            if self.game_started: return
            self.game_started = True
            
            self.current_holder = random.choice(self.alive_players)
            self.bomb_timer = random.uniform(self.min_timer, self.max_timer)
            
            name = self.players[self.current_holder]['name']
            print(f"[GAME] Debut - Bombe sur {name}")
            self.add_event('game_start', f"Debut de partie - {name} a la bombe")
            
            self.send_to_player(self.current_holder, {
                'type': 'RECEIVE_BOMB',
                'timer': self.bomb_timer,
                'available_targets': self.get_available_targets(self.current_holder)
            })
            self.broadcast_game_state()

    def pass_bomb(self, from_socket, target_id):
        with self.lock:
            if from_socket != self.current_holder: return

            target_socket = next((s for s, info in self.players.items() if info['id'] == target_id and info['alive']), None)
            if not target_socket: return

            from_n = self.players[from_socket]['name']
            to_n = self.players[target_socket]['name']
            
            self.current_holder = target_socket
            print(f"[PASS] {from_n} -> {to_n}")
            self.add_event('bomb_passed', f"{from_n} passe a {to_n}")

            self.send_to_player(target_socket, {
                'type': 'RECEIVE_BOMB',
                'timer': self.bomb_timer,
                'from': from_n,
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
        if not self.current_holder: return
        
        victim = self.players[self.current_holder]
        print(f"[BOOM] {victim['name']} a explose")
        self.add_event('explosion', f"BOOM - {victim['name']} elimine")

        victim['alive'] = False
        self.alive_players.remove(self.current_holder)

        self.broadcast({
            'type': 'EXPLODE',
            'victim': victim['name'],
            'survivors': [self.players[s]['name'] for s in self.alive_players]
        })

        if len(self.alive_players) == 1:
            winner = self.players[self.alive_players[0]]['name']
            print(f"[WIN] {winner} gagne")
            self.add_event('winner', f"Victoire de {winner}")
            self.broadcast({'type': 'WINNER', 'winner': winner})
            threading.Thread(target=self.reset_game).start()
        elif self.alive_players:
            self.current_holder = random.choice(self.alive_players)
            self.bomb_timer = random.uniform(self.min_timer, self.max_timer)
            self.send_to_player(self.current_holder, {
                'type': 'RECEIVE_BOMB',
                'timer': self.bomb_timer,
                'available_targets': self.get_available_targets(self.current_holder)
            })
            self.broadcast_game_state()

    def get_available_targets(self, current_socket):
        return [info['id'] for sock, info in self.players.items() if sock != current_socket and info['alive']]

    def broadcast_game_state(self):
        state = {
            'type': 'GAME_STATE',
            'players': [{'name': info['name'], 'alive': info['alive']} for info in self.players.values()],
            'current_holder': self.players[self.current_holder]['name'] if self.current_holder else None,
            'timer': round(self.bomb_timer, 1) if self.game_started else 0
        }
        self.broadcast(state)

    def broadcast(self, message):
        payload = (json.dumps(message) + '\n').encode('utf-8')
        bad_sockets = []
        for sock in list(self.players.keys()):
            try:
                sock.sendall(payload)
            except:
                bad_sockets.append(sock)
        for s in bad_sockets: self.remove_player(s)

    def send_to_player(self, sock, message):
        try:
            sock.sendall((json.dumps(message) + '\n').encode('utf-8'))
        except: pass

    def remove_player(self, sock):
        with self.lock:
            if sock in self.players:
                name = self.players[sock]['name']
                print(f"[LEAVE] {name} est parti")
                self.add_event('leave', f"{name} a quitte la partie")
                
                if sock in self.alive_players:
                    self.alive_players.remove(sock)
                
                if sock == self.current_holder:
                    self.current_holder = random.choice(self.alive_players) if self.alive_players else None
                    self.bomb_timer = random.uniform(self.min_timer, self.max_timer)
                
                del self.players[sock]

    def reset_game(self):
        time.sleep(5)
        with self.lock:
            self.game_started = False
            self.current_holder = None
            for info in self.players.values(): info['alive'] = True
            self.alive_players = list(self.players.keys())
            
            if len(self.alive_players) >= self.min_players:
                print("[SYSTEM] Nouvelle partie")
                self.start_game()

if __name__ == '__main__':
    server = BombGameServer()
    server.start()
import socket
import json
import threading
import time
import random
import os
import sys

class BombPlayer:
    def __init__(self):
        self.player_name = os.getenv('PLAYER_NAME', f'Player_{random.randint(1000, 9999)}')
        self.player_id = self.player_name.lower().replace(' ', '_')
        self.server_host = os.getenv('SERVER_HOST', 'localhost')
        self.server_port = int(os.getenv('SERVER_PORT', 5000))
        # Temps de réaction simulé
        self.reaction_time = float(os.getenv('REACTION_TIME', random.uniform(1, 4)))
        
        self.socket = None
        self.has_bomb = False
        self.available_targets = []
        
        # Verrou pour éviter que deux threads écrivent dans le socket en même temps
        self.lock = threading.Lock() 

    def connect(self):
        max_retries = 10
        retry_delay = 3
        
        for attempt in range(max_retries):
            try:
                print(f"Tentative de connexion ({attempt + 1}/{max_retries})...")
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.server_host, self.server_port))
                
                join_message = {
                    'type': 'JOIN',
                    'player_id': self.player_id,
                    'player_name': self.player_name
                }
                self.send_message(join_message)
                
                print(f"Connecté au serveur en tant que {self.player_name}")
                return True
                
            except Exception as e:
                print(f"Échec de connexion: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    print("Impossible de se connecter au serveur")
                    return False
    
    def run(self):
        if not self.connect():
            return
        
        try:
            buffer = ""
            while True:
                # Lecture bloquante standard
                data = self.socket.recv(4096).decode('utf-8')
                if not data:
                    print("Connexion perdue avec le serveur")
                    break
                
                buffer += data
                
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            message = json.loads(line)
                            self.handle_message(message)
                        except json.JSONDecodeError as e:
                            print(f"Erreur JSON: {e}")
                
        except Exception as e:
            print(f"Erreur critique: {e}")
        finally:
            if self.socket:
                self.socket.close()
            print(f"{self.player_name} a quitté la partie")
    
    def handle_message(self, message):
        msg_type = message['type']
        
        if msg_type == 'RECEIVE_BOMB':
            self.receive_bomb(message)
        
        elif msg_type == 'GAME_STATE':
            self.display_game_state(message)
        
        elif msg_type == 'EXPLODE':
            victim = message['victim']
            if victim == self.player_name:
                print(f"\nBOOOM ! Vous avez explosé !\n")
                self.has_bomb = False # Important : on n'a plus la bombe
            else:
                print(f"\n{victim} a explosé !")
                survivors = message['survivors']
                print(f"Survivants: {', '.join(survivors)}\n")
        
        elif msg_type == 'WINNER':
            winner = message['winner']
            if winner == self.player_name:
                print(f"\nVICTOIRE ! Vous avez gagné !\n")
            else:
                print(f"\n{winner} a gagné la partie\n")
    
    def receive_bomb(self, message):
        self.has_bomb = True
        timer = message['timer']
        self.available_targets = message.get('available_targets', [])
        
        from_player = message.get('from', 'le serveur')
        print(f"\nVous avez reçu la BOMBE de {from_player} !")
        print(f"Timer: {timer:.1f}s")
        
        # Calcul du temps de "réflexion"
        wait_time = min(self.reaction_time, timer * 0.7)
        print(f"Réflexion pendant {wait_time:.1f}s...")
        
        # IMPORTANT: Utilisation d'un Timer pour ne pas bloquer la boucle de lecture
        t = threading.Timer(wait_time, self._execute_pass_bomb)
        t.start()
        
    def _execute_pass_bomb(self):
        """Cette fonction est appelée par le thread Timer après le délai"""
        # Vérification critique : a-t-on toujours la bombe ?
        if not self.has_bomb:
            return

        if self.available_targets:
            target = random.choice(self.available_targets)
            self.pass_bomb(target)
        else:
            print("Aucune cible disponible pour passer la bombe !")

    def pass_bomb(self, target_id):
        # Double sécurité
        if not self.has_bomb:
            return
        
        print(f"Passage de la bombe à {target_id}...")
        
        message = {
            'type': 'PASS_BOMB',
            'from': self.player_id,
            'to': target_id
        }
        
        if self.send_message(message):
            self.has_bomb = False
    
    def display_game_state(self, state):
        players = state['players']
        current_holder = state.get('current_holder')
        timer = state.get('timer', 0)
        
        # On peut décommenter pour voir l'état en temps réel
        # print(f"DEBUG: État reçu. Porteur: {current_holder}")
    
    def send_message(self, message):
        """Envoie un message de manière thread-safe"""
        try:
            data = (json.dumps(message) + '\n').encode('utf-8')
            # Le verrou assure que le thread principal et le thread Timer
            # ne mélangent pas leurs données dans le socket
            with self.lock:
                self.socket.sendall(data)
            return True
        except Exception as e:
            print(f"Erreur d'envoi: {e}")
            return False

if __name__ == '__main__':
    try:
        player = BombPlayer()
        player.run()
    except KeyboardInterrupt:
        print("\nArrêt manuel du joueur.")
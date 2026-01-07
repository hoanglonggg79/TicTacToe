import pygame, sys, os, random, math, json, socket, threading, queue, time
from math import inf
from datetime import datetime

os.environ['SDL_IM_MODULE'] = 'ibus'

pygame.init()
try:
    pygame.mixer.init()
except:
    pass

BASE_DIR = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
def path(*relative):
    return os.path.join(BASE_DIR, "assets", *relative)

# ======================= SETTINGS (global cooldown) ============================
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {
            "volume": 100,
            "theme": "default",
            "last_player_name": "",
            "lan_cooldown_until": 0
        }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "lan_cooldown_until" not in data:
                data["lan_cooldown_until"] = 0
            return data
    except Exception:
        return {
            "volume": 100,
            "theme": "default",
            "last_player_name": "",
            "lan_cooldown_until": 0
        }

def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print("Lỗi lưu settings:", e)

# Ensure settings.json exists at startup (creates an innocuous file)
if not os.path.exists(SETTINGS_FILE):
    save_settings(load_settings())

# ======================= ACHIEVEMENTS (new) ===================================
ACH_FILE = os.path.join(BASE_DIR, "achievements.json")

def default_achievements():
    return {
        "win_ai_hard": 0,
        "rematch_after_lose": False,
        "first_challenge": False,
        "peace_accepted": False,
        "peace_rejected": False
    }

def load_achievements():
    if not os.path.exists(ACH_FILE):
        # create initial file
        try:
            with open(ACH_FILE, "w", encoding="utf-8") as f:
                json.dump(default_achievements(), f, ensure_ascii=False, indent=2)
        except:
            pass
        return default_achievements()
    try:
        with open(ACH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # ensure keys exist
            base = default_achievements()
            for k, v in base.items():
                if k not in data:
                    data[k] = v
            return data
    except:
        return default_achievements()

def save_achievements(data):
    try:
        with open(ACH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Lỗi lưu achievements:", e)

# Achievement definitions (localized)
ACH_DEFS = {
    # sequential count achievements for winning AI Hard
    "win_ai_1": {"name": {"vi": "[START] Não To Lộ Diện", "en": "[START] Big Brain Revealed"}, "legendary": False},
    "win_ai_3": {"name": {"vi": "[AMATEUR] Não To Có Trình", "en": "[AMATEUR] Big Brain Pro"}, "legendary": False},
    "win_ai_10": {"name": {"vi": "[AI] Kẻ Khiến AI Do Dự", "en": "[AI] AI Hesitator"}, "legendary": False},
    "win_ai_20": {"name": {"vi": "[TACTICS] Ông Hoàng Chiến Thuật", "en": "[TACTICS] Tactics Overlord"}, "legendary": False},
    "win_ai_50": {"name": {"vi": "[ALGORITHM] Kẻ Bẻ Cong Thuật Toán", "en": "[ALGORITHM] Algorithm Bender"}, "legendary": True},
    "win_ai_100": {"name": {"vi": "[KING] Huyền Thoại Phòng Máy", "en": "[KING] Arcade Legend"}, "legendary": True},

    # single-shot
    "first_peace_request": {"name": {"vi": "[DRAW] Hòa Trong Danh Dự", "en": "[DRAW] An Honorable Draw"}, "legendary": False},
    "peace_rejected": {"name": {"vi": "[DENY] Đối Thủ Chưa Tha", "en": "[DENY] No Mercy from the Opponent"}, "legendary": False},
    "peace_accepted": {"name": {"vi": "[PEACE] Cái Bắt Tay Thành Công", "en": "[PEACE] A Successful Handshake"}, "legendary": False},
    "rematch_after_lose": {"name": {"vi": "[TRY] Không Cam Tâm", "en": "[TRY] Not Ready to Give Up"}, "legendary": False}
}

# helper to map win count to achievement id (ordered thresholds)
WIN_AI_THRESHOLDS = [
    (1, "win_ai_1"),
    (3, "win_ai_3"),
    (10, "win_ai_10"),
    (20, "win_ai_20"),
    (50, "win_ai_50"),
    (100, "win_ai_100")
]

# ======================= NETWORK MANAGER =====================================
class NetworkManager:
    def __init__(self):
        self.client = None
        self.server = None
        self.port = 5555
        self.connected = False
        self.is_host = False
        self.peer_addr = None
        self.msg_queue = queue.Queue()
        self.buffer = ""
        self.disconnected_midgame = False
        self.remote_sent_left = False

    @staticmethod
    def _is_private_ip(ip):
        """
        Return True if ip is inside private ranges:
        10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, link-local 169.254.0.0/16.
        """
        try:
            parts = ip.split(".")
            if len(parts) != 4:
                return False
            a, b, c, d = map(int, parts)
            if a == 10:
                return True
            if a == 172 and 16 <= b <= 31:
                return True
            if a == 192 and b == 168:
                return True
            if a == 169 and b == 254:
                return True
            return False
        except Exception:
            return False

    def get_local_ip(self):
        """
        Improved local IP detection:
        - Gather candidate IPv4 addresses from hostname resolution and probing multiple endpoints.
        - Prefer private addresses (192.168.*, 10.*, 172.16-31.*).
        - Fallback to previous 'connect-to-8.8.8.8' trick if nothing else found.
        This is more robust when WARP/VPN is active because we probe local gateways
        and prioritize typical LAN addresses.
        """
        candidates = set()

        # 1) Addresses from gethostbyname_ex (may include LAN addresses)
        try:
            host = socket.gethostname()
            try:
                _, _, addrs = socket.gethostbyname_ex(host)
                for a in addrs:
                    if a and not a.startswith("127."):
                        candidates.add(a)
            except:
                pass
        except:
            pass

        # 2) Probe several endpoints (public DNS and common home gateways) to get the source addr used
        probes = [
            ("8.8.8.8", 80),   # Google DNS (outbound)
            ("1.1.1.1", 80),   # Cloudflare DNS (outbound)
            ("8.8.4.4", 80),
            ("192.168.1.1", 80),  # typical gateway
            ("192.168.0.1", 80),
            ("10.0.0.1", 80)
        ]
        for host, port in probes:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.5)
                s.connect((host, port))
                ip = s.getsockname()[0]
                s.close()
                if ip and not ip.startswith("127."):
                    candidates.add(ip)
            except:
                try:
                    s.close()
                except:
                    pass
                continue

        # 3) If we found private addresses, prefer them and prefer more-likely LAN ranges
        private_candidates = [ip for ip in candidates if self._is_private_ip(ip)]
        if private_candidates:
            # Prefer 192.168.*, then 10.*, then 172.16-31.*
            def score(ip):
                if ip.startswith("192.168."):
                    return 3
                if ip.startswith("10."):
                    return 2
                if ip.startswith("172."):
                    try:
                        second = int(ip.split(".")[1])
                        if 16 <= second <= 31:
                            return 1
                    except:
                        return 0
                return 0
            private_candidates.sort(key=score, reverse=True)
            return private_candidates[0]

        # 4) If no private found, but we have candidates (maybe WARP or public IP), choose a non-loopback candidate
        for ip in candidates:
            if not ip.startswith("127."):
                return ip

        # 5) Fallback to original technique
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip:
                return ip
        except:
            pass

        return "127.0.0.1"

    def start_server(self):
        self.is_host = True
        self.disconnected_midgame = False
        self.remote_sent_left = False
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.bind(('0.0.0.0', self.port))
            self.server.listen(1)
            threading.Thread(target=self.wait_for_client, daemon=True).start()
            return True
        except Exception as e:
            print(f"Lỗi tạo server: {e}")
            return False

    def wait_for_client(self):
        try:
            self.client, addr = self.server.accept()
            self.peer_addr = addr
            self.connected = True
            threading.Thread(target=self.receive_loop, daemon=True).start()
            self.msg_queue.put(("sys", "connected"))
        except:
            pass

    def connect_to_server(self, ip):
        self.is_host = False
        self.disconnected_midgame = False
        self.remote_sent_left = False
        try:
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.connect((ip, self.port))
            self.connected = True
            threading.Thread(target=self.receive_loop, daemon=True).start()
            self.msg_queue.put(("sys", "connected"))
            return True
        except Exception as e:
            print(f"Lỗi kết nối: {e}")
            return False

    def receive_loop(self):
        while self.connected:
            try:
                data = self.client.recv(4096).decode()
                if not data:
                    # remote closed cleanly
                    self.connected = False
                    self.msg_queue.put(("sys", "disconnect"))
                    break

                self.buffer += data
                while "|" in self.buffer:
                    msg, self.buffer = self.buffer.split("|", 1)
                    if not msg:
                        continue

                    if msg.startswith("move:"):
                        parts = msg.split(":")[1].split(",")
                        self.msg_queue.put(("move", (int(parts[0]), int(parts[1]))))
                    elif msg == "restart":
                        # restart is disabled for LAN - ignore or optionally notify
                        self.msg_queue.put(("net_restart", None))
                    elif msg.startswith("chat:"):
                        content = msg.split("chat:", 1)[1]
                        self.msg_queue.put(("chat", content))
                    elif msg.startswith("name:"):
                        name = msg.split("name:", 1)[1]
                        self.msg_queue.put(("name", name))
                    elif msg.startswith("left:"):
                        name = msg.split("left:", 1)[1]
                        self.remote_sent_left = True
                        self.msg_queue.put(("left", name))
                    elif msg == "REQ_REMATCH":
                        self.msg_queue.put(("net_req_rematch", None))
                    elif msg == "ACCEPT_REMATCH":
                        self.msg_queue.put(("net_accept_rematch", None))
                    elif msg == "DENY_REMATCH":
                        self.msg_queue.put(("net_deny_rematch", None))
                    elif msg == "OFFER_DRAW":
                        self.msg_queue.put(("offer_draw", None))
                    elif msg == "ACCEPT_DRAW":
                        self.msg_queue.put(("accept_draw", None))
                    elif msg == "DENY_DRAW":
                        self.msg_queue.put(("deny_draw", None))
                    elif msg.startswith("opponent_quit"):
                        # format: "opponent_quit:NAME" or just "opponent_quit"
                        name = None
                        if ":" in msg:
                            try:
                                name = msg.split(":", 1)[1]
                            except:
                                name = None
                        self.msg_queue.put(("opponent_quit", name))

            except:
                # network error / sudden disconnect
                self.connected = False
                self.disconnected_midgame = True
                self.msg_queue.put(("sys", "disconnect"))
                break

    def send_raw(self, msg):
        if self.client and self.connected:
            try:
                self.client.send(f"{msg}|".encode())
            except:
                self.connected = False
                self.disconnected_midgame = True

    def send_move(self, r, c):
        self.send_raw(f"move:{r},{c}")

    def send_restart(self):
        # disabled for LAN per requirement
        pass

    # REMATCH messages (enabled for LAN)
    def send_rematch_req(self):
        self.send_raw("REQ_REMATCH")

    def send_rematch_accept(self):
        self.send_raw("ACCEPT_REMATCH")

    def send_rematch_deny(self):
        self.send_raw("DENY_REMATCH")

    # DRAW OFFER messages
    def send_offer_draw(self):
        self.send_raw("OFFER_DRAW")

    def send_accept_draw(self):
        self.send_raw("ACCEPT_DRAW")

    def send_deny_draw(self):
        self.send_raw("DENY_DRAW")

    def send_chat(self, msg):
        self.send_raw(f"chat:{msg.replace('|', '')}")

    def send_name(self, name):
        self.send_raw(f"name:{name.replace('|', '')}")

    def send_left(self, name):
        # legacy "left" message (remote closed intentionally)
        self.send_raw(f"left:{name.replace('|','')}")

    def send_opponent_quit(self, name):
        # explicit intentional quit notification (so opponent can be awarded win but NOT penalized)
        self.send_raw(f"opponent_quit:{name.replace('|','') if name else ''}")

    def close(self):
        self.connected = False
        try:
            if self.client:
                self.client.close()
        except:
            pass
        try:
            if self.server:
                self.server.close()
        except:
            pass

# ======================= PARTICLE & LEADERBOARD ==============================
class Particle:
    def __init__(self, x, y, color):
        self.x = x
        self.y = y
        self.color = color
        angle = random.uniform(0, 6.28)
        speed = random.uniform(2, 6)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.radius = random.randint(3, 6)
        self.life = 1.0
        self.decay = random.uniform(0.01, 0.03)
        self.gravity = 0.1

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += self.gravity
        self.life -= self.decay
        self.radius = max(0, self.radius - 0.05)

    def draw(self, screen):
        if self.life > 0 and self.radius > 0:
            alpha = int(self.life * 255)
            s = pygame.Surface((int(self.radius*2), int(self.radius*2)), pygame.SRCALPHA)
            pygame.draw.circle(s, (*self.color, alpha), (int(self.radius), int(self.radius)), int(self.radius))
            screen.blit(s, (int(self.x) - self.radius, int(self.y) - self.radius))

class Leaderboard:
    def __init__(self):
        self.save_dir = os.path.join(BASE_DIR, "save")
        self.save_file = os.path.join(self.save_dir, "leaderboard.json")
        self.ensure_save_dir()
        self.scores = self.load_scores()

    def ensure_save_dir(self):
        if not os.path.exists(self.save_dir):
            try:
                os.makedirs(self.save_dir)
            except Exception as e:
                print(f"Lỗi tạo folder save: {e}")

    def load_scores(self):
        if not os.path.exists(self.save_file):
            return []
        try:
            with open(self.save_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    def save_scores(self):
        try:
            with open(self.save_file, 'w', encoding='utf-8') as f:
                json.dump(self.scores, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Lỗi lưu file: {e}")

    def add_or_update_score(self, player_name, score_x, score_o, mode):
        if "LAN" in mode or "Online" in mode:
            return

        existing_entry = next((item for item in self.scores if item["name"].lower() == player_name.lower()), None)
        current_total = score_x + score_o
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        if existing_entry:
            existing_entry["score_x"] = score_x
            existing_entry["score_o"] = score_o
            existing_entry["total"] = current_total
            existing_entry["mode"] = mode
            existing_entry["date"] = timestamp
            existing_entry["name"] = player_name
        else:
            entry = {
                "name": player_name, "score_x": score_x, "score_o": score_o,
                "total": current_total, "mode": mode, "date": timestamp
            }
            self.scores.append(entry)
        self.scores.sort(key=lambda x: x["total"], reverse=True)
        self.scores = self.scores[:10]
        self.save_scores()

# ======================= CONFIG & TEXTS =====================================
class Config:
    BOARD_SIZE = 15
    WIN_CONDITION = 5
    ALLOW_BLOCKED_WIN = False
    GAP = 1
    BOTTOM_BAR = 120

    HEIGHT = 650
    CELL_SIZE = (HEIGHT - BOTTOM_BAR) // BOARD_SIZE
    WIDTH = BOARD_SIZE * CELL_SIZE
    FPS = 60

    PIXEL_FONT_FILE = path("font", "PixelOperator.ttf")
    SYSTEM_FONT_FILE = path("font", "arial.ttf")

    def safe_load_font(path, size):
        try:
            return pygame.font.Font(path, size)
        except:
            return pygame.font.SysFont("arial", size)

    FONT_XO = safe_load_font(PIXEL_FONT_FILE, CELL_SIZE * 8 // 10)
    FONT_UI_SMALL = safe_load_font(SYSTEM_FONT_FILE, 16)
    FONT_UI_MED = safe_load_font(SYSTEM_FONT_FILE, 22)
    FONT_UI_MSG = safe_load_font(SYSTEM_FONT_FILE, 32)
    FONT_CHAT = safe_load_font(SYSTEM_FONT_FILE, 14)
    FONT_BIG = safe_load_font(SYSTEM_FONT_FILE, 42)

    MUSIC_MENU_FILE = path("music", "a.mp3")
    MUSIC_GAME_FILE = path("music", "b.mp3")
    CLICK_FILE = path("music", "click.wav")
    WIN_SOUND_FILE = path("music", "win.mp3")
    LOSE_SOUND_FILE = path("music", "lose.mp3")
    TING_SOUND_FILE = path("music", "ting.mp3")

    BG_COLOR = (232, 217, 192)
    CELL_BG = (246, 238, 222)
    WOOD_BORDER = (170, 125, 80)
    GRID_LINE = (120, 82, 45)
    X_COLOR = (180, 30, 30)
    O_COLOR = (120, 65, 130)
    HIGHLIGHT_LINE = (230, 60, 60)
    HOVER_COLOR = (255, 236, 153)
    BTN_BG = (205, 180, 140)
    BTN_TEXT = (50, 30, 20)
    MSG_COLOR = (120, 30, 30)
    SCORE_BG = (220, 200, 170)
    TUTORIAL_BG = (255, 250, 240)
    TUTORIAL_TEXT = (40, 40, 40)
    CHAT_BG = (255, 255, 255, 200)
    CHAT_TEXT = (0, 0, 0)

    VICTORY_QUOTES_VI = [
        "{winner} thắng rồi!",
        "Thua rồi,{loser}!",
        "{winner} quá mạnh!",
        "GG EZ - {winner}",
        "{loser} luyện thêm đi!",
        "Đẳng cấp quá {winner}!"
    ]

    VICTORY_QUOTES_EN = [
        "{winner} wins!",
        "{loser} lost!",
        "{winner} too strong!",
        "GG EZ - {winner}",
        "{loser} needs practice!",
        "{winner}'s level!"
    ]

    TEXTS = {
        "title": {"vi": "Tic Tac Toe - HoangLong", "en": "Tic Tac Toe - HoangLong"},
        "play_2p": {"vi": "Chơi 2 người", "en": "Play 2 Player"},
        "play_ai": {"vi": "Chơi với máy (AI)", "en": "Play with AI"},
        "play_online": {"vi": "Đấu LAN (Wifi)", "en": "Play Online (LAN)"},
        "leaderboard": {"vi": "Bảng Xếp Hạng", "en": "Leaderboard"},
        "tutorial": {"vi": "Hướng Dẫn", "en": "Tutorial"},
        "ai_select_title": {"vi": ">> Chọn Độ Khó AI <<", "en": ">> Select Difficulty <<"},
        "ai_easy": {"vi": "AI Dễ (Ngẫu nhiên)", "en": "Easy AI (Random)"},
        "ai_hard": {"vi": "AI Khó (Minimax 3-ply)", "en": "Hard AI (Minimax)"},
        "quit": {"vi": "Thoát", "en": "Quit"},
        "hint": {"vi": "Game Đang Trong Giai Đoạn Phát Triển", "en": "The game is in development"},
        "lang_btn": {"vi": "Ngôn ngữ:", "en": "Language:"},
        "restart": {"vi": "Chơi Lại", "en": "Restart"},
        "menu_back": {"vi": "Menu", "en": "Menu"},
        "undo": {"vi": "Đi Lại", "en": "Undo"},
        "turn_of": {"vi": "Lượt của:", "en": "Turn of:"},
        "win_x": {"vi": "Người chơi X thắng!", "en": "Player X wins!"},
        "win_o": {"vi": "Người chơi O thắng!", "en": "Player O wins!"},
        "draw": {"vi": "Hòa rồi!", "en": "It's a Draw!"},
        "back": {"vi": "Quay Lại", "en": "Back"},
        "leaderboard_title": {"vi": "--- BẢNG XẾP HẠNG ---", "en": "--- LEADERBOARD ---"},
        "rank": {"vi": "Hạng", "en": "Rank"},
        "name": {"vi": "Tên", "en": "Name"},
        "total": {"vi": "Tổng Ván", "en": "Total"},
        "mode": {"vi": "Chế độ", "en": "Mode"},
        "date": {"vi": "Ngày", "en": "Date"},
        "no_scores": {"vi": "Chưa có điểm nào!", "en": "No scores yet!"},
        "save_score_prompt": {"vi": "Lưu điểm? Nhập tên:", "en": "Save score? Enter name:"},
        "mode_2p": {"vi": "2 Người", "en": "2 Player"},
        "mode_ai_easy": {"vi": "AI Dễ", "en": "AI Easy"},
        "mode_ai_hard": {"vi": "AI Khó", "en": "AI Hard"},
        "mode_online": {"vi": "LAN", "en": "LAN"},
        "online_title": {"vi": ">> CHẾ ĐỘ ONLINE <<", "en": ">> ONLINE MODE <<"},
        "host_game": {"vi": "Tạo Phòng (Host)", "en": "Create Room (Host)"},
        "join_game": {"vi": "Vào Phòng (Client)", "en": "Join Room (Client)"},
        "enter_ip": {"vi": "Nhập IP Máy Chủ:", "en": "Enter Host IP:"},
        "waiting_conn": {"vi": "Đang chờ kết nối...", "en": "Waiting for player..."},
        "your_ip": {"vi": "IP của bạn:", "en": "Your IP:"},
        "connect_fail": {"vi": "Kết nối thất bại!", "en": "Connection Failed!"},
        "you_are": {"vi": "Bạn là:", "en": "You are:"},
        "tutorial_title": {"vi": "[ HƯỚNG DẪN CHƠI ]", "en": "[ HOW TO PLAY ]"},
        "tut_1": {"vi": ">> MỤC TIÊU:", "en": ">> OBJECTIVE:"},
        "tut_1_desc": {"vi": "Xếp 5 quân cờ liên tiếp theo hàng ngang, dọc hoặc chéo", "en": "Align 5 pieces in a row (horizontal, vertical, or diagonal)"},
        "tut_2": {"vi": ">> CÁCH CHƠI:", "en": ">> HOW TO PLAY:"},
        "tut_2_desc": {"vi": "- Click vào ô trống để đánh\n- X đi trước, O đi sau\n- Luân phiên đánh cho đến khi có người thắng", "en": "- Click empty cell to place\n- X goes first, O goes second\n- Take turns until someone wins"},
        "tut_3": {"vi": ">> TÍNH NĂNG:", "en": ">> FEATURES:"},
        "tut_3_desc": {"vi": "- Undo: Đi lại nước đã đánh\n- Score: Điểm được lưu qua các ván\n- Leaderboard: Bảng xếp hạng điểm cao", "en": "- Undo: Take back your move\n- Score: Points saved across games\n- Leaderboard: High score ranking"},
        "tut_4": {"vi": ">> CHẾ ĐỘ AI:", "en": ">> AI MODES:"},
        "tut_4_desc": {"vi": "- AI Dễ: Đánh ngẫu nhiên\n- AI Khó: Sử dụng thuật toán Minimax", "en": "- Easy AI: Random moves\n- Hard AI: Uses Minimax algorithm"},
        "tut_5": {"vi": ">> MẸO:", "en": ">> TIPS:"},
        "tut_5_desc": {"vi": "- Kiểm soát trung tâm bàn cờ\n- Tạo nhiều hàng đồng thời\n- Chặn đối thủ khi họ sắp thắng", "en": "- Control the center of the board\n- Create multiple threats at once\n- Block opponent when they're close to winning"},
        "tut_chat": {"vi": ">> CHAT LAN:", "en": ">> LAN CHAT:"},
        "tut_chat_desc": {"vi": "- Nhấn ENTER để bật khung chat\n- Gõ tin nhắn và nhấn ENTER để gửi", "en": "- Press ENTER to open chat box\n- Type and press ENTER to send"},
        "enter_name_lan": {"vi": "Nhập biệt danh thi đấu:", "en": "Enter your battle name:"},
        "rematch_request": {"vi": "{name} muốn tái đấu!", "en": "{name} wants a rematch!"},
        "rematch_accept": {"vi": "[ENTER] Đồng ý | [ESC] Từ chối ({sec}s)", "en": "[ENTER] Accept | [ESC] Decline ({sec}s)"},
        "rematch_btn": {"vi": "Yêu Cầu Tái Đấu", "en": "Request Rematch"},
        "waiting_response": {"vi": "Đang chờ phản hồi...", "en": "Waiting for response..."},
        "rematch_denied": {"vi": "Đối phương từ chối tái đấu.", "en": "Opponent declined rematch."},
        # new
        "cooldown_wait": {"vi": "Vui lòng chờ {sec}s trước khi chơi LAN", "en": "Please wait {sec}s before playing LAN"},
        "disconnect_penalty": {"vi": "Phát hiện bạn, {name} rời trận. Chờ {sec}s để chơi LAN tiếp.", "en": "Detected you, {name}, left mid-game. Wait {sec}s before joining LAN again."},
        "opponent_left": {"vi": "Người chơi {name} đã thoát. Bạn được xử thắng!", "en": "Player {name} left. You've been awarded the win!"},
        "you_left_lose": {"vi": "Bạn đã rời trận khi tới lượt — xử thua.", "en": "You left mid-game during your turn — you forfeit."},
        # draw offer texts
        "draw_offer": {"vi": "{name} đề nghị hòa", "en": "{name} offers a draw"},
        "draw_offer_accept": {"vi": "[ENTER] Đồng ý | [ESC] Từ chối ({sec}s)", "en": "[ENTER] Accept | [ESC] Decline ({sec}s)"},
        "draw_agreed": {"vi": "Đã đồng ý hòa", "en": "Draw agreed"},
        "draw_denied": {"vi": "Đối phương từ chối hòa", "en": "Opponent declined draw"}
    }

    def safe_load_sound(path):
        if not os.path.exists(path):
            return None
        try:
            return pygame.mixer.Sound(path)
        except:
            return None

    CLICK_SOUND = safe_load_sound(CLICK_FILE)
    WIN_SOUND = safe_load_sound(WIN_SOUND_FILE)
    LOSE_SOUND = safe_load_sound(LOSE_SOUND_FILE)
    TING_SOUND = safe_load_sound(TING_SOUND_FILE)

# ======================= BOARD, AI (updated logic) ============================
class Board:
    def __init__(self, size, win_cond, allow_blocked):
        self.size = size
        self.win_cond = win_cond
        self.allow_blocked = allow_blocked
        self.reset()

    def reset(self):
        self.grid = [["" for _ in range(self.size)] for _ in range(self.size)]
        self.winning_line = None
        self.winning_cells = []
        self.place_animations = {}

    def cell_rect(self, r, c):
        x = c * Config.CELL_SIZE
        y = r * Config.CELL_SIZE
        return pygame.Rect(x + Config.GAP, y + Config.GAP, Config.CELL_SIZE - Config.GAP * 2, Config.CELL_SIZE - Config.GAP * 2)

    def pixel_center(self, r, c):
        return (c * Config.CELL_SIZE + Config.CELL_SIZE // 2, r * Config.CELL_SIZE + Config.CELL_SIZE // 2)

    def draw(self, screen, game_state, current_player, mouse_pos):
        screen.fill(Config.BG_COLOR)
        for r in range(self.size):
            for c in range(self.size):
                rect = self.cell_rect(r, c)
                pygame.draw.rect(screen, Config.CELL_BG, rect)
                pygame.draw.rect(screen, Config.WOOD_BORDER, rect, 1)

        if game_state == "game" and not self.winning_line and mouse_pos[1] < self.size * Config.CELL_SIZE:
            col = mouse_pos[0] // Config.CELL_SIZE
            row = mouse_pos[1] // Config.CELL_SIZE
            if 0 <= row < self.size and 0 <= col < self.size and self.grid[row][col] == "":
                pygame.draw.rect(screen, Config.HOVER_COLOR, self.cell_rect(row, col))
                color = Config.X_COLOR if current_player == "X" else Config.O_COLOR
                surf = Config.FONT_XO.render(current_player, True, color)
                surf.set_alpha(100)
                center = self.pixel_center(row, col)
                screen.blit(surf, (center[0] - surf.get_width() // 2, center[1] - surf.get_height() // 2))

        now = pygame.time.get_ticks()
        to_delete = []
        for r in range(self.size):
            for c in range(self.size):
                v = self.grid[r][c]
                if v == "":
                    continue
                center = self.pixel_center(r, c)
                color = Config.X_COLOR if v == "X" else Config.O_COLOR
                surf = Config.FONT_XO.render(v, True, color)
                key = (r, c)
                scale = 1.0
                if key in self.place_animations:
                    start, dur = self.place_animations[key]
                    elapsed = now - start
                    if elapsed < dur:
                        t = elapsed / dur
                        scale = 1.6 - 0.6 * t
                    else:
                        scale = 1.0
                        to_delete.append(key)

                if scale != 1.0:
                    sw = max(1, int(surf.get_width() * scale))
                    sh = max(1, int(surf.get_height() * scale))
                    surf = pygame.transform.scale(surf, (sw, sh))

                screen.blit(surf, (center[0] - surf.get_width() // 2, center[1] - surf.get_height() // 2))

        for key in to_delete:
            del self.place_animations[key]

    def draw_highlight(self, screen, flash_phase):
        if not self.winning_line:
            return
        if flash_phase % 2 == 1:
            for (r, c) in self.winning_cells:
                rct = self.cell_rect(r, c)
                pygame.draw.rect(screen, Config.HOVER_COLOR, rct.inflate(-4, -4))
            pygame.draw.line(screen, Config.HIGHLIGHT_LINE, self.winning_line[0], self.winning_line[1], 8)

    def check_winner(self):
        result, cells, line = self.check_winner_pure(self.grid)
        self.winning_cells = cells
        self.winning_line = line
        return result

    def check_winner_pure(self, grid):
        dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]
        size = self.size
        win_cond = self.win_cond

        for r in range(size):
            for c in range(size):
                p = grid[r][c]
                if p == "":
                    continue
                for dr, dc in dirs:
                    count = 1
                    sr, sc = r, c
                    er, ec = r, c
                    rr, cc = r + dr, c + dc
                    while 0 <= rr < size and 0 <= cc < size and grid[rr][cc] == p:
                        count += 1
                        er, ec = rr, cc
                        rr += dr; cc += dc
                    rr, cc = r - dr, c - dc
                    while 0 <= rr < size and 0 <= cc < size and grid[rr][cc] == p:
                        count += 1
                        sr, sc = rr, cc
                        rr -= dr; cc -= dc
                    if count >= win_cond:
                        if not self.allow_blocked:
                            prev_r, prev_c = sr - dr, sc - dc
                            next_r, next_c = er + dr, ec + dc
                            blocked_start = 0 <= prev_r < size and 0 <= prev_c < size and grid[prev_r][prev_c] != "" and grid[prev_r][prev_c] != p
                            blocked_end = 0 <= next_r < size and 0 <= next_c < size and grid[next_r][next_c] != "" and grid[next_r][next_c] != p
                            if blocked_start and blocked_end:
                                continue
                        cells = []
                        rr, cc = sr, sc
                        for _ in range(count):
                            cells.append((rr, cc))
                            rr += dr; cc += dc
                        line_start = (sc * Config.CELL_SIZE + Config.CELL_SIZE // 2, sr * Config.CELL_SIZE + Config.CELL_SIZE // 2)
                        line_end = (ec * Config.CELL_SIZE + Config.CELL_SIZE // 2, er * Config.CELL_SIZE + Config.CELL_SIZE // 2)
                        return p, cells, (line_start, line_end)
        return None, [], None

# Improved HardAI: Minimax with alpha-beta, limited candidate moves, pattern-aware heuristic and Zobrist TT
class HardAI:
    """
    Faster Hard AI with:
    - Immediate win/block checks
    - Iterative deepening with time limit
    - Beam search (limit branching) using quick heuristic ordering
    - Zobrist TT (transposition table)
    Designed as a drop-in replacement for the previous HardAI.
    Tune: self.MAX_CANDIDATES, self.BEAM_WIDTH, self.TIME_LIMIT, self.max_depth
    """
    def __init__(self, board):
        self.board = board
        # Base max depth for full minimax (will do iterative deepening up to this)
        self.max_depth = 3  # keep small by default for speed; can set 4 if CPU ok
        self.ai_char = "O"
        self.opp_char = "X"

        # Performance parameters (tune to trade speed vs strength)
        self.TIME_LIMIT = 0.5        # seconds per move (iterative deepening stops when exceeded)
        self.MAX_CANDIDATES = 18    # initial candidate count (top N from quick scoring)
        self.BEAM_WIDTH = 10        # number of children considered at deeper nodes (smaller -> faster)

        # Zobrist table for hashing
        self.zobrist_table = [[(random.getrandbits(64), random.getrandbits(64)) for _ in range(board.size)] for _ in range(board.size)]
        self.tt = {}  # zobrist_key -> (stored_depth, stored_value)

        # Pattern weights (simplified but strong enough)
        self.PATTERN_WEIGHTS = {
            'FIVE': 100_000_000,
            'OPEN4': 1_000_000,
            'CLOSED4': 15_000,
            'OPEN3': 10_000,
            'OPEN2': 100,
            'SINGLE': 5
        }

    def compute_zobrist(self):
        h = 0
        for r in range(self.board.size):
            for c in range(self.board.size):
                v = self.board.grid[r][c]
                if v == "X":
                    h ^= self.zobrist_table[r][c][0]
                elif v == "O":
                    h ^= self.zobrist_table[r][c][1]
        return h

    def available_moves(self):
        return [(r, c) for r in range(self.board.size) for c in range(self.board.size) if self.board.grid[r][c] == ""]

    def find_winning_move_for(self, player_char):
        for r in range(self.board.size):
            for c in range(self.board.size):
                if self.board.grid[r][c] == "":
                    self.board.grid[r][c] = player_char
                    winner, _, _ = self.board.check_winner_pure(self.board.grid)
                    self.board.grid[r][c] = ""
                    if winner == player_char:
                        return (r, c)
        return None

    def _quick_score_cell(self, r, c):
        """
        Very cheap local heuristic to rank moves for candidate generation and ordering.
        Counts adjacent stones in 4 directions, favors blocking opponent slightly.
        """
        s = 0
        size = self.board.size
        for dr, dc in [(0,1),(1,0),(1,1),(1,-1)]:
            ai_cnt = 0
            opp_cnt = 0
            for k in (1,2):
                rr = r + dr * k
                cc = c + dc * k
                if 0 <= rr < size and 0 <= cc < size:
                    if self.board.grid[rr][cc] == self.ai_char:
                        ai_cnt += 1
                    elif self.board.grid[rr][cc] == self.opp_char:
                        opp_cnt += 1
                rr = r - dr * k
                cc = c - dc * k
                if 0 <= rr < size and 0 <= cc < size:
                    if self.board.grid[rr][cc] == self.ai_char:
                        ai_cnt += 1
                    elif self.board.grid[rr][cc] == self.opp_char:
                        opp_cnt += 1
            s += ai_cnt * 10 - opp_cnt * 12  # prefer blocking slightly more
        # center preference
        center = self.board.size // 2
        dist = abs(r-center) + abs(c-center)
        s += max(0, (self.board.size//2 - dist))
        return s

    def _scan_runs(self, grid, player):
        # reuse scanning logic similar to improved AI (returns runs for pattern detection)
        runs = []
        size = self.board.size
        dirs = [(0,1),(1,0),(1,1),(1,-1)]
        for r in range(size):
            for c in range(size):
                if grid[r][c] != player:
                    continue
                for dr, dc in dirs:
                    prev_r, prev_c = r - dr, c - dc
                    if 0 <= prev_r < size and 0 <= prev_c < size and grid[prev_r][prev_c] == player:
                        continue
                    cnt = 1
                    rr, cc = r + dr, c + dc
                    while 0 <= rr < size and 0 <= cc < size and grid[rr][cc] == player:
                        cnt += 1
                        rr += dr; cc += dc
                    left_r, left_c = r - dr, c - dc
                    right_r, right_c = rr, cc
                    left_empty = (0 <= left_r < size and 0 <= left_c < size and grid[left_r][left_c] == "")
                    right_empty = (0 <= right_r < size and 0 <= right_c < size and grid[right_r][right_c] == "")
                    left_pos = (left_r, left_c) if left_empty else None
                    right_pos = (right_r, right_c) if right_empty else None
                    runs.append({
                        'length': cnt,
                        'left_empty': left_empty,
                        'right_empty': right_empty,
                        'left_pos': left_pos,
                        'right_pos': right_pos
                    })
        return runs

    def find_urgent_block_cells(self):
        """
        Returns cells that block opponent's dangerous runs (len>=3), so we can prioritize/short-circuit.
        """
        urgent = set()
        runs = self._scan_runs(self.board.grid, self.opp_char)
        for run in runs:
            ln = run['length']
            if ln >= 3:
                if run['left_pos']:
                    urgent.add(run['left_pos'])
                if run['right_pos']:
                    urgent.add(run['right_pos'])
            elif ln == 2 and run['left_pos'] and run['right_pos']:
                # include open-2 endpoints as lower-priority (helps choose sensible moves)
                urgent.add(run['left_pos'])
                urgent.add(run['right_pos'])
        urgent.discard(None)
        return list(urgent)

    def generate_candidate_moves(self, max_candidates=None):
        """
        Generate candidate moves around existing stones; use quick scoring and include urgent blocks.
        max_candidates overrides self.MAX_CANDIDATES if provided.
        """
        if max_candidates is None:
            max_candidates = self.MAX_CANDIDATES

        size = self.board.size
        existing = [(r, c) for r in range(size) for c in range(size) if self.board.grid[r][c] != ""]
        if not existing:
            center = size // 2
            return [(center, center)]

        urgent = set(self.find_urgent_block_cells())

        neighbors = set()
        R = 2
        for (er, ec) in existing:
            for dr in range(-R, R+1):
                for dc in range(-R, R+1):
                    r = er + dr
                    c = ec + dc
                    if 0 <= r < size and 0 <= c < size and self.board.grid[r][c] == "":
                        neighbors.add((r, c))
        if not neighbors:
            neighbors = set(self.available_moves())

        scored = []
        for (r, c) in neighbors:
            base = self._quick_score_cell(r, c)
            if (r, c) in urgent:
                base += 200000  # force urgent to top
            scored.append(((r, c), base))
        scored.sort(key=lambda x: x[1], reverse=True)
        candidates = [p for p, s in scored[:max_candidates]]

        # ensure urgent ones included (and placed at front)
        for u in urgent:
            if u in candidates:
                # move to front
                candidates.remove(u)
                candidates.insert(0, u)
            else:
                candidates.insert(0, u)
        # unique preserve order
        final = []
        seen = set()
        for p in candidates:
            if p not in seen and 0 <= p[0] < size and 0 <= p[1] < size:
                final.append(p)
                seen.add(p)
        return final

    def evaluate(self):
        """
        Pattern-based evaluation similar to the improved AI but cheap enough for frequent calls.
        """
        def score_for(player):
            total = 0
            runs = self._scan_runs(self.board.grid, player)
            for run in runs:
                cnt = run['length']
                left_empty = run['left_empty']
                right_empty = run['right_empty']
                openness = 2 if left_empty and right_empty else 1 if left_empty or right_empty else 0
                if cnt >= self.board.win_cond:
                    w = self.PATTERN_WEIGHTS['FIVE']
                elif cnt == 4:
                    w = self.PATTERN_WEIGHTS['OPEN4'] if openness == 2 else self.PATTERN_WEIGHTS['CLOSED4']
                elif cnt == 3:
                    w = self.PATTERN_WEIGHTS['OPEN3'] if openness == 2 else (self.PATTERN_WEIGHTS['OPEN3'] // 3)
                elif cnt == 2:
                    w = self.PATTERN_WEIGHTS['OPEN2'] if openness == 2 else (self.PATTERN_WEIGHTS['OPEN2'] // 4)
                elif cnt == 1:
                    w = self.PATTERN_WEIGHTS['SINGLE']
                else:
                    w = 0
                total += w
            return total

        ai_score = score_for(self.ai_char)
        opp_score = score_for(self.opp_char)

        # dynamic weighting: if opponent has runs >=3, weight defense more
        opp_runs = self._scan_runs(self.board.grid, self.opp_char)
        max_opp_len = 0
        for r in opp_runs:
            if r['length'] > max_opp_len:
                max_opp_len = r['length']
        if max_opp_len >= 4:
            opp_factor = 2.5
        elif max_opp_len == 3:
            opp_factor = 2.0
        else:
            opp_factor = 1.5
        return ai_score - opp_factor * opp_score

    def _minimax(self, depth, alpha, beta, maximizing, beam_width):
        """
        Minimax with alpha-beta and beam_width limiting child count.
        beam_width controls how many children to expand (move ordering used).
        """
        key = self.compute_zobrist()
        entry = self.tt.get(key)
        if entry is not None:
            stored_depth, stored_value = entry
            if stored_depth >= depth:
                return stored_value

        winner, _, _ = self.board.check_winner_pure(self.board.grid)
        if winner == self.ai_char:
            return self.PATTERN_WEIGHTS['FIVE']
        if winner == self.opp_char:
            return -self.PATTERN_WEIGHTS['FIVE']
        if depth == 0:
            val = self.evaluate()
            self.tt[key] = (depth, val)
            return val

        # generate limited candidates for this node
        # reduce max candidates as depth increases (beam search)
        max_cand = beam_width if depth <= 1 else min(self.MAX_CANDIDATES, beam_width)
        moves = self.generate_candidate_moves(max_candidates=max_cand)
        if not moves:
            return 0

        # order moves by quick eval for better pruning
        ordered = []
        for mv in moves:
            r,c = mv
            # simulate cheap: put AI's perspective for maximizing else opponent
            self.board.grid[r][c] = self.ai_char if maximizing else self.opp_char
            val = self._fast_partial_eval(r, c)
            self.board.grid[r][c] = ""
            ordered.append((mv, val))
        ordered.sort(key=lambda x: x[1], reverse=maximizing)
        ordered_moves = [mv for mv, _ in ordered][:beam_width]

        if maximizing:
            value = -inf
            for (r, c) in ordered_moves:
                self.board.grid[r][c] = self.ai_char
                val = self._minimax(depth-1, alpha, beta, False, beam_width)
                self.board.grid[r][c] = ""
                if val > value:
                    value = val
                alpha = max(alpha, val)
                if alpha >= beta:
                    break
            self.tt[key] = (depth, value)
            return value
        else:
            value = inf
            for (r, c) in ordered_moves:
                self.board.grid[r][c] = self.opp_char
                val = self._minimax(depth-1, alpha, beta, True, beam_width)
                self.board.grid[r][c] = ""
                if val < value:
                    value = val
                beta = min(beta, val)
                if alpha >= beta:
                    break
            self.tt[key] = (depth, value)
            return value

    def _fast_partial_eval(self, r, c):
        """
        Very cheap local heuristic used for move ordering: returns heuristic value
        based on adjacency, used only for ordering children.
        """
        return self._quick_score_cell(r, c)

    def get_move(self):
        # Immediate win
        mv = self.find_winning_move_for(self.ai_char)
        if mv:
            return mv
        # Immediate block of opponent win
        mv = self.find_winning_move_for(self.opp_char)
        if mv:
            return mv

        # urgent blocking cells (if only 1 urgent cell, play it immediately)
        urgent = self.find_urgent_block_cells()
        if len(urgent) == 1:
            return urgent[0]

        # iterative deepening with time limit
        start_time = time.time()
        best_move = None
        best_score = -inf

        # initial candidate set (small)
        candidates = self.generate_candidate_moves(max_candidates=self.MAX_CANDIDATES)
        if not candidates:
            moves = self.available_moves()
            return random.choice(moves) if moves else None

        # order candidates by quick heuristic
        candidates.sort(key=lambda mv: self._quick_score_cell(mv[0], mv[1]), reverse=True)

        # iterative deepening from depth 1..max_depth
        for depth in range(1, self.max_depth + 1):
            # if time exceeded, stop
            if time.time() - start_time > self.TIME_LIMIT:
                break
            # try each candidate, but respect time
            for (r, c) in candidates:
                if time.time() - start_time > self.TIME_LIMIT:
                    break
                # play
                self.board.grid[r][c] = self.ai_char
                score = self._minimax(depth-1, -inf, inf, False, self.BEAM_WIDTH)
                self.board.grid[r][c] = ""
                if score is None:
                    continue
                if score > best_score:
                    best_score = score
                    best_move = (r, c)
            # small optimization: if we found a forced win, break early
            if best_score >= self.PATTERN_WEIGHTS['OPEN4']:
                break

        # fallback
        if best_move:
            return best_move
        moves = self.available_moves()
        return random.choice(moves) if moves else None

# EasyAI: keep it 'easy' but with simple heuristics so it doesn't play totally random
class EasyAI:
    def __init__(self, board):
        self.board = board
        self.ai_char = "O"
        self.opp_char = "X"

    def find_winning_move_for(self, player_char):
        for r in range(self.board.size):
            for c in range(self.board.size):
                if self.board.grid[r][c] == "":
                    self.board.grid[r][c] = player_char
                    winner, _, _ = self.board.check_winner_pure(self.board.grid)
                    self.board.grid[r][c] = ""
                    if winner == player_char:
                        return (r, c)
        return None

    def nearby_moves(self, radius=2):
        size = self.board.size
        existing = [(r, c) for r in range(size) for c in range(size) if self.board.grid[r][c] != ""]
        if not existing:
            center = size // 2
            return [(center, center)]
        cand = set()
        for er, ec in existing:
            for dr in range(-radius, radius+1):
                for dc in range(-radius, radius+1):
                    r = er + dr
                    c = ec + dc
                    if 0 <= r < size and 0 <= c < size and self.board.grid[r][c] == "":
                        cand.add((r, c))
        return list(cand) if cand else [(r, c) for r in range(size) for c in range(size) if self.board.grid[r][c] == ""]

    def score_move_simple(self, r, c):
        # simple score: count adjacent O and X in radius 1
        s = 0
        for dr, dc in [(0,1),(1,0),(1,1),(1,-1),(0,-1),(-1,0),(-1,-1),(-1,1)]:
            rr = r + dr
            cc = c + dc
            if 0 <= rr < self.board.size and 0 <= cc < self.board.size:
                if self.board.grid[rr][cc] == self.ai_char:
                    s += 3
                elif self.board.grid[rr][cc] == self.opp_char:
                    s += 1
        # prefer center slightly
        center = self.board.size // 2
        dist = abs(r-center) + abs(c-center)
        s += max(0, (self.board.size//2 - dist) // 2)
        return s

    def get_move(self):
        # immediate win
        mv = self.find_winning_move_for(self.ai_char)
        if mv:
            return mv
        # immediate block
        mv = self.find_winning_move_for(self.opp_char)
        if mv:
            return mv

        moves = self.nearby_moves()
        if not moves:
            moves = [(r, c) for r in range(self.board.size) for c in range(self.board.size) if self.board.grid[r][c] == ""]

        # score candidates simply and pick best usually; sometimes pick random to stay 'easy'
        scored = [(self.score_move_simple(r, c), (r, c)) for (r, c) in moves]
        scored.sort(key=lambda x: x[0], reverse=True)
        # 70% choose best, 30% random among top 6
        if random.random() < 0.7:
            return scored[0][1]
        else:
            top = [p for s, p in scored[:6]] if len(scored) >= 6 else [p for s, p in scored]
            return random.choice(top) if top else None

# ======================= GAME CLASS ==========================================
class Game:
    REMATCH_TIMEOUT_MS = 10000
    DRAW_OFFER_TIMEOUT_MS = 10000

    TROPHY_RECT = pygame.Rect(Config.WIDTH-110, Config.HEIGHT-110, 80, 80)

    def __init__(self, screen, clock):
        self.screen = screen
        self.clock = clock
        self.board = Board(Config.BOARD_SIZE, Config.WIN_CONDITION, Config.ALLOW_BLOCKED_WIN)
        self.ai = None
        self.ai_level = "hard"
        self.lang = "vi"
        self.music_on = True
        self.state = "menu"
        self.ai_enabled = False

        # Networking
        self.network = NetworkManager()
        self.online_mode = False
        self.online_role = None
        self.input_ip = ""
        self.error_msg = ""

        # Player Names
        self.my_name = "Player"
        self.opp_name = "???"
        self.input_name_lan_str = ""

        # Chat
        self.chat_history = []
        self.chat_input = ""
        self.typing_chat = False
        self.chat_timeout = 15000

        # REMATCH SYSTEM (for LAN)
        self.rematch_request_sent = False   # we sent rematch request (waiting)
        self.rematch_incoming = False      # someone requested rematch to us
        self.rematch_timer_ms = 0
        self.rematch_requester = None

        # DRAW OFFER SYSTEM
        self.draw_offer_sent = False
        self.draw_offer_incoming = False
        self.draw_offer_timer_ms = 0
        self.draw_offer_requester = None

        self.waiting_for_response = False
        self.rematch_btn_rect = pygame.Rect(0, 0, 1, 1)

        # SCREEN SHAKE
        self.shake_offset = [0, 0]
        self.shake_intensity = 0

        # TRASH TALK
        self.final_trash_talk = ""

        self.player = "X"
        self.game_over = False
        self.winner = None
        self.move_history = []
        self.scores = {"X": 0, "O": 0}

        self.flash_phase = 0
        self.flash_interval = 300
        self.last_flash_time = 0

        self.particles = []
        self.leaderboard = Leaderboard()
        self.show_save_prompt = False
        self.player_name_input = ""
        self.cached_player_name = None

        # Achievements
        self.achievements = load_achievements()
        self.achievement_popup = None  # dict: { 'title','reason','end_time','legendary','icon' }
        self.achievement_popup_duration = 2500  # ms
        self.recent_unlock_pulse = 0  # stronger trophy pulse when unlocked recently

        # UI rects
        self.restart_rect = pygame.Rect(0, 0, 1, 1)
        self.menuback_rect = pygame.Rect(0, 0, 1, 1)
        self.music_rect = pygame.Rect(0, 0, 1, 1)
        self.undo_rect = pygame.Rect(0, 0, 1, 1)

        self.play_rect = pygame.Rect(0, 0, 1, 1)
        self.ai_select_rect = pygame.Rect(0, 0, 1, 1)
        self.online_btn_rect = pygame.Rect(0, 0, 1, 1)
        self.leaderboard_rect = pygame.Rect(0, 0, 1, 1)
        self.tutorial_rect = pygame.Rect(0, 0, 1, 1)
        self.lang_rect = pygame.Rect(0, 0, 1, 1)
        self.quit_rect = pygame.Rect(0, 0, 1, 1)

        self.easy_ai_rect = pygame.Rect(0, 0, 1, 1)
        self.hard_ai_rect = pygame.Rect(0, 0, 1, 1)
        self.back_ai_rect = pygame.Rect(0, 0, 1, 1)
        self.back_leaderboard_rect = pygame.Rect(0, 0, 1, 1)
        self.back_tutorial_rect = pygame.Rect(0, 0, 1, 1)

        self.host_rect = pygame.Rect(0, 0, 1, 1)
        self.join_rect = pygame.Rect(0, 0, 1, 1)
        self.back_online_rect = pygame.Rect(0, 0, 1, 1)

        # offer draw button rect
        self.offer_draw_rect = pygame.Rect(0, 0, 1, 1)

        # center message for mid-screen notifications
        self.center_message = ""
        self.center_message_time = 0  # milliseconds

        # distinguish intentional quit vs sudden disconnect
        self.intentional_quit = False

        # cached settings for apply_ban
        self.settings = load_settings()

        # Achievements scroll state
        self.ach_scroll = 0
        self.ach_dragging = False
        self.ach_drag_start_y = 0
        self.ach_drag_start_scroll = 0
        self.ach_item_height = 80          # height used per achievement entry (match draw_achievements_menu)
        self.ach_view_top = 100            # top Y where achievement list starts
        self.ach_view_bottom_margin = 90   # margin from bottom for the list area

    def get_text(self, key):
        return Config.TEXTS.get(key, {}).get(self.lang, key)

    def play_click(self):
        if Config.CLICK_SOUND:
            try:
                Config.CLICK_SOUND.play()
            except:
                pass

    def play_end_sound(self):
        try:
            if self.winner == "X":
                if Config.WIN_SOUND:
                    Config.WIN_SOUND.play()
            elif self.winner == "O":
                if self.ai_enabled and Config.LOSE_SOUND:
                    Config.LOSE_SOUND.play()
                elif Config.WIN_SOUND:
                    Config.WIN_SOUND.play()
            elif self.game_over and Config.LOSE_SOUND:
                Config.LOSE_SOUND.play()
        except:
            pass

    def start_music(self):
        if not self.music_on:
            return
        music_file = Config.MUSIC_GAME_FILE if self.state == "game" else Config.MUSIC_MENU_FILE
        if not os.path.exists(music_file):
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(music_file)
            pygame.mixer.music.set_volume(0.45)
            pygame.mixer.music.play(-1, 0.0)
        except Exception as e:
            print(f"Lỗi: {e}")

    def stop_music(self):
        try:
            pygame.mixer.music.stop()
        except:
            pass

    def create_win_particles(self):
        if not self.board.winning_cells:
            return
        target_cells = self.board.winning_cells
        if len(target_cells) > 3:
            target_cells = random.sample(self.board.winning_cells, 3)
        for r, c in target_cells:
            center = self.board.pixel_center(r, c)
            color = Config.X_COLOR if self.winner == "X" else Config.O_COLOR
            for _ in range(30):
                self.particles.append(Particle(center[0], center[1], color))

    def update_particles(self):
        for p in self.particles[:]:
            p.update()
            if p.life <= 0:
                self.particles.remove(p)

    def draw_particles(self):
        for p in self.particles:
            p.draw(self.screen)

    def trigger_screen_shake(self, intensity=10):
        self.shake_intensity = intensity

    def update_screen_shake(self):
        if self.shake_intensity > 0:
            self.shake_offset = [
                random.randint(-self.shake_intensity, self.shake_intensity),
                random.randint(-self.shake_intensity, self.shake_intensity)
            ]
            self.shake_intensity -= 1
        else:
            self.shake_offset = [0, 0]

    def apply_shake_offset(self, surface):
        if self.shake_offset != [0, 0]:
            temp = pygame.Surface((Config.WIDTH, Config.HEIGHT))
            temp.blit(surface, self.shake_offset)
            return temp
        return surface

    def get_trash_talk_message(self):
        quotes = Config.VICTORY_QUOTES_VI if self.lang == "vi" else Config.VICTORY_QUOTES_EN
        msg = random.choice(quotes)
        if self.online_mode:
            winner_name = self.my_name if self.winner == self.online_role else self.opp_name
            loser_name = self.opp_name if self.winner == self.online_role else self.my_name
        else:
            winner_name = self.winner
            loser_name = "O" if self.winner == "X" else "X"
        return msg.format(winner=winner_name, loser=loser_name)

    def reset_game(self, ai_mode=False, online_mode=False):
        self.board.reset()
        self.player = "X"
        self.game_over = False
        self.winner = None
        self.move_history = []
        self.particles = []
        self.flash_phase = 0
        self.ai_enabled = ai_mode
        self.online_mode = online_mode
        self.state = "game"
        self.show_save_prompt = False
        self.player_name_input = ""

        self.chat_history = []
        self.chat_input = ""
        self.typing_chat = False

        # reset rematch/draw flags
        self.rematch_request_sent = False
        self.rematch_incoming = False
        self.rematch_timer_ms = 0
        self.rematch_requester = None
        self.waiting_for_response = False

        self.draw_offer_sent = False
        self.draw_offer_incoming = False
        self.draw_offer_timer_ms = 0
        self.draw_offer_requester = None

        self.rematch_requested = False
        self.rematch_timer = 0
        self.waiting_for_response = False

        self.final_trash_talk = ""

        # reset intentional flag when starting a fresh round
        self.intentional_quit = False

        if self.network:
            self.network.disconnected_midgame = False
            self.network.remote_sent_left = False

        if ai_mode:
            if self.ai_level == "easy":
                self.ai = EasyAI(self.board)
            else:
                self.ai = HardAI(self.board)
        else:
            self.ai = None
        self.start_music()

    def undo_move(self):
        if self.online_mode:
            return
        if self.game_over or not self.move_history:
            return

        def pop_one():
            if not self.move_history:
                return
            r, c = self.move_history.pop()
            self.board.grid[r][c] = ""
            if (r, c) in self.board.place_animations:
                del self.board.place_animations[(r, c)]

        if self.ai_enabled:
            pop_one()
            pop_one()
            self.player = "X"
        else:
            pop_one()
            self.player = "O" if self.player == "X" else "X"
        self.play_click()

    def go_to_menu(self):
        self.state = "menu"
        self.show_save_prompt = False
        self.cached_player_name = None

        was_online = self.online_mode
        self.online_mode = False
        self.online_role = None
        if was_online:
            self.network.close()
        self.start_music()

    def go_to_ai_select(self):
        self.state = "ai_select"
        self.cached_player_name = None

    def go_to_leaderboard(self):
        self.state = "leaderboard"

    def go_to_tutorial(self):
        self.state = "tutorial"

    def go_to_online_select(self):
        self.state = "online_select"

    def toggle_music(self):
        self.music_on = not self.music_on
        if self.music_on:
            self.start_music()
        else:
            self.stop_music()

    def save_score_to_leaderboard(self):
        name = self.player_name_input.strip()
        if not name and self.cached_player_name:
            name = self.cached_player_name
        if not name:
            name = "Player"
        self.cached_player_name = name

        mode = ""
        if self.online_mode:
            mode = self.get_text("mode_online")
        elif not self.ai_enabled:
            mode = self.get_text("mode_2p")
        elif self.ai_level == "easy":
            mode = self.get_text("mode_ai_easy")
        else:
            mode = self.get_text("mode_ai_hard")

        self.leaderboard.add_or_update_score(name, self.scores["X"], self.scores["O"], mode)
        self.show_save_prompt = False
        self.player_name_input = ""

    # cooldown check (global)
    def is_lan_cooldown_active(self):
        settings = load_settings()
        now = time.time()
        cooldown_until = settings.get("lan_cooldown_until", 0)
        if now < cooldown_until:
            return int(cooldown_until - now)
        return 0

    # apply global cooldown (writes to settings.json) - simplified util
    def apply_ban(self, duration_seconds, name=None):
        settings = load_settings()
        settings.setdefault("volume", 100)
        settings.setdefault("theme", "default")
        settings["lan_cooldown_until"] = time.time() + duration_seconds
        settings["last_player_name"] = name if name else self.my_name
        save_settings(settings)
        nm = name if name else self.my_name
        self.error_msg = self.get_text("disconnect_penalty").format(name=nm, sec=duration_seconds)
        self.center_message = self.get_text("disconnect_penalty").format(name=nm, sec=duration_seconds)
        self.center_message_time = 5000  # ms

    # REMATCH / achievements integration
    def request_rematch(self):
        # for LAN only: send request and wait
        if not self.online_mode:
            return
        if not self.game_over:
            return
        # only loser can request: ensure local player is loser
        if not self.winner:
            return
        loser_role = "X" if self.winner == "O" else "O"
        if self.online_role != loser_role:
            # not the loser
            return
        try:
            self.network.send_rematch_req()
            self.rematch_request_sent = True
            self.waiting_for_response = True
            self.center_message = self.get_text("waiting_response")
            self.center_message_time = 3000
            # Achievement: first rematch after lose
            if not self.achievements.get("rematch_after_lose", False):
                self.achievements["rematch_after_lose"] = True
                save_achievements(self.achievements)
                title = ACH_DEFS["rematch_after_lose"]["name"].get(self.lang, ACH_DEFS["rematch_after_lose"]["name"]["en"])
                reason = {"vi": "Gửi yêu cầu tái đấu lần đầu", "en": "Sent rematch request (first time)"}[self.lang]
                legendary = ACH_DEFS["rematch_after_lose"]["legendary"]
                self.show_achievement_popup(title, reason, legendary)
        except:
            self.center_message = "Failed to send rematch request"
            self.center_message_time = 3000

    def add_chat_msg(self, msg):
        self.chat_history.append({'text': msg, 'time': pygame.time.get_ticks()})

    def start_new_round(self):
        # note: rematch logic for LAN handled externally
        self.board.reset()
        self.player = "X"
        self.game_over = False
        self.winner = None
        self.move_history = []
        self.particles = []
        self.flash_phase = 0
        self.rematch_requested = False
        self.rematch_timer = 0
        self.waiting_for_response = False
        self.final_trash_talk = ""

    # Achievement popup
    def show_achievement_popup(self, title, reason, legendary=False, icon="[ACH]"):
        self.achievement_popup = {
            "title": title,
            "reason": reason,
            "end_time": pygame.time.get_ticks() + self.achievement_popup_duration,
            "legendary": legendary,
            "icon": icon
        }
        # increase trophy pulse indicator
        self.recent_unlock_pulse = 120  # frames of stronger pulse

    def draw_achievement_popup(self):
        if not self.achievement_popup:
            return
        now = pygame.time.get_ticks()
        if now > self.achievement_popup["end_time"]:
            self.achievement_popup = None
            return
        # draw translucent dark overlay (60-70%)
        overlay = pygame.Surface((Config.WIDTH, Config.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        # box centered, slightly below center
        box_w, box_h = 520, 120
        box_x = (Config.WIDTH - box_w) // 2
        box_y = (Config.HEIGHT - box_h) // 2 + 20

        # background
        s = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        s.fill((30, 30, 30, 220))
        # border
        pygame.draw.rect(s, (220, 200, 120) if self.achievement_popup["legendary"] else (240, 240, 240), (0,0,box_w,box_h), 2, border_radius=8)

        # icon left
        icon_text = Config.FONT_BIG.render(self.achievement_popup["icon"], True, (255, 215, 0))
        s.blit(icon_text, (18, box_h//2 - icon_text.get_height()//2))

        # title (gold if legendary)
        title_color = (255, 215, 0) if self.achievement_popup["legendary"] else (255, 255, 255)
        title_font = Config.FONT_UI_MSG
        title_surf = title_font.render(self.achievement_popup["title"], True, title_color)
        s.blit(title_surf, (110, 20))

        reason_font = Config.FONT_UI_SMALL
        reason_surf = reason_font.render(self.achievement_popup["reason"], True, (200, 200, 200))
        s.blit(reason_surf, (110, 60))

        self.screen.blit(s, (box_x, box_y))

    # Draw trophy icon in menu (blinking pulse)
    def draw_trophy_icon(self):
        rect = Game.TROPHY_RECT
        t = pygame.time.get_ticks() / 1000.0
        # base alpha pulse
        base_alpha = 150 + int(105 * abs(math.sin(t * 2)))
        # if recent unlock, stronger pulse
        if self.recent_unlock_pulse > 0:
            extra = 80 + int(80 * abs(math.sin(t * 6)))
            alpha = min(255, base_alpha + extra)
            self.recent_unlock_pulse -= 1
        else:
            alpha = base_alpha

        trophy_surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        # dark rounded bg
        pygame.draw.rect(trophy_surf, (40, 40, 40, alpha), (0, 0, rect.width, rect.height), border_radius=12)

        # icon
        icon = Config.FONT_BIG.render("[ACH]", True, (255, 215, 0))
        trophy_surf.blit(icon, (rect.width//2 - icon.get_width()//2, rect.height//2 - icon.get_height()//2 - 4))

        # small badge if there are new unlocked achievements (we'll show gold dot)
        # check if any unlocked (achievements that are True or count>0)
        unlocked_any = False
        for k, v in self.achievements.items():
            if isinstance(v, bool) and v:
                unlocked_any = True
                break
            if isinstance(v, int) and v > 0:
                unlocked_any = True
                break
        if unlocked_any:
            pygame.draw.circle(trophy_surf, (255, 215, 0, 220), (rect.width-16, 16), 8)

        self.screen.blit(trophy_surf, rect.topleft)

    def draw_menu(self):
        self.screen.fill(Config.BG_COLOR)
        title = Config.FONT_UI_MSG.render(self.get_text("title"), True, Config.GRID_LINE)
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 20))
        btn_w, btn_h = 300, 45
        start_y = 90
        gap = 8
        self.play_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, start_y, btn_w, btn_h)
        self.ai_select_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, start_y + btn_h + gap, btn_w, btn_h)
        self.online_btn_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, start_y + 2*(btn_h + gap), btn_w, btn_h)
        self.leaderboard_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, start_y + 3*(btn_h + gap), btn_w, btn_h)
        self.tutorial_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, start_y + 4*(btn_h + gap), btn_w, btn_h)
        self.lang_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, start_y + 5*(btn_h + gap), btn_w, btn_h)
        self.quit_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, start_y + 6*(btn_h + gap), btn_w, btn_h)

        buttons = [
            (self.play_rect, "play_2p"),
            (self.ai_select_rect, "play_ai"),
            (self.online_btn_rect, "play_online"),
            (self.leaderboard_rect, "leaderboard"),
            (self.tutorial_rect, "tutorial"),
            (self.lang_rect, None),
            (self.quit_rect, "quit")
        ]

        for rect, key in buttons:
            pygame.draw.rect(self.screen, Config.BTN_BG, rect)
            pygame.draw.rect(self.screen, Config.WOOD_BORDER, rect, 2)
            if key is None:
                lang_display = "Tiếng Việt" if self.lang == "vi" else "ENGLISH"
                txt = Config.FONT_UI_MED.render(f"{self.get_text('lang_btn')} {lang_display}", True, Config.BTN_TEXT)
            else:
                txt_str = self.get_text(key)
                if key == "play_2p":
                    txt_str = f"{txt_str} ({Config.BOARD_SIZE}x{Config.BOARD_SIZE})"
                txt = Config.FONT_UI_MED.render(txt_str, True, Config.BTN_TEXT)
            self.screen.blit(txt, (rect.centerx - txt.get_width() // 2, rect.centery - txt.get_height() // 2))
        hint = Config.FONT_UI_SMALL.render(self.get_text("hint"), True, Config.GRID_LINE)
        self.screen.blit(hint, (Config.WIDTH // 2 - hint.get_width() // 2, Config.HEIGHT - 30))

        # trophy (achievements) icon bottom-right
        self.draw_trophy_icon()

    def draw_input_name_lan(self):
        self.screen.fill(Config.BG_COLOR)
        title = Config.FONT_UI_MSG.render(self.get_text("enter_name_lan"), True, Config.GRID_LINE)
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 200))
        box = pygame.Rect(Config.WIDTH//2 - 150, 260, 300, 50)
        pygame.draw.rect(self.screen, (255, 255, 255), box)
        pygame.draw.rect(self.screen, Config.WOOD_BORDER, box, 2)
        txt = Config.FONT_UI_MED.render(self.input_name_lan_str, True, (0,0,0))
        self.screen.blit(txt, (box.x + 10, box.y + 10))
        hint = Config.FONT_UI_SMALL.render("ENTER: OK | ESC: Back", True, Config.GRID_LINE)
        self.screen.blit(hint, (Config.WIDTH // 2 - hint.get_width() // 2, 330))

    def draw_online_select(self):
        self.screen.fill(Config.BG_COLOR)
        title = Config.FONT_UI_MSG.render(self.get_text("online_title"), True, Config.GRID_LINE)
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 40))

        btn_w, btn_h = 350, 60
        self.host_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, 140, btn_w, btn_h)
        self.join_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, 220, btn_w, btn_h)
        self.back_online_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, 380, btn_w, btn_h)

        for rect, txt_key in [(self.host_rect, "host_game"), (self.join_rect, "join_game"), (self.back_online_rect, "menu_back")]:
            pygame.draw.rect(self.screen, Config.BTN_BG, rect)
            pygame.draw.rect(self.screen, Config.WOOD_BORDER, rect, 2)
            txt = Config.FONT_UI_MED.render(self.get_text(txt_key), True, Config.BTN_TEXT)
            self.screen.blit(txt, (rect.centerx - txt.get_width() // 2, rect.centery - txt.get_height() // 2))

    def draw_input_ip(self):
        self.screen.fill(Config.BG_COLOR)
        title = Config.FONT_UI_MSG.render(self.get_text("enter_ip"), True, Config.GRID_LINE)
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 100))

        box_w, box_h = 300, 50
        input_box = pygame.Rect((Config.WIDTH - box_w)//2, 180, box_w, box_h)
        pygame.draw.rect(self.screen, (255, 255, 255), input_box)
        pygame.draw.rect(self.screen, Config.WOOD_BORDER, input_box, 2)

        txt = Config.FONT_UI_MED.render(self.input_ip, True, Config.BTN_TEXT)
        self.screen.blit(txt, (input_box.x + 10, input_box.y + 10))

        hint = Config.FONT_UI_SMALL.render("Enter: Connect | Esc: Back", True, Config.GRID_LINE)
        self.screen.blit(hint, (Config.WIDTH // 2 - hint.get_width() // 2, 250))

        if self.error_msg:
            err = Config.FONT_UI_SMALL.render(self.error_msg, True, Config.X_COLOR)
            self.screen.blit(err, (Config.WIDTH // 2 - err.get_width() // 2, 300))

    def draw_waiting(self):
        self.screen.fill(Config.BG_COLOR)
        title = Config.FONT_UI_MSG.render(self.get_text("waiting_conn"), True, Config.GRID_LINE)
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 120))

        ip_txt = f"{self.get_text('your_ip')} {self.network.get_local_ip()}"
        sub = Config.FONT_UI_MED.render(ip_txt, True, Config.O_COLOR)
        self.screen.blit(sub, (Config.WIDTH // 2 - sub.get_width() // 2, 180))

        name_txt = Config.FONT_UI_SMALL.render(f"Playing as: {self.my_name}", True, Config.BTN_TEXT)
        self.screen.blit(name_txt, (Config.WIDTH // 2 - name_txt.get_width() // 2, 230))

        hint = Config.FONT_UI_SMALL.render("Esc: Cancel", True, Config.GRID_LINE)
        self.screen.blit(hint, (Config.WIDTH // 2 - hint.get_width() // 2, 300))

    def draw_ai_select(self):
        self.screen.fill(Config.BG_COLOR)
        title = Config.FONT_UI_MSG.render(self.get_text("ai_select_title"), True, Config.GRID_LINE)
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 26))
        btn_w, btn_h = 350, 60
        self.easy_ai_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, 120, btn_w, btn_h)
        self.hard_ai_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, 200, btn_w, btn_h)
        self.back_ai_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, 360, btn_w, btn_h)
        if self.ai_level == "easy":
            pygame.draw.rect(self.screen, Config.HIGHLIGHT_LINE, self.easy_ai_rect.inflate(8, 8), 4)
        else:
            pygame.draw.rect(self.screen, Config.HIGHLIGHT_LINE, self.hard_ai_rect.inflate(8, 8), 4)
        for rect in [self.easy_ai_rect, self.hard_ai_rect, self.back_ai_rect]:
            pygame.draw.rect(self.screen, Config.BTN_BG, rect)
        easy_txt = Config.FONT_UI_MED.render(self.get_text("ai_easy"), True, Config.BTN_TEXT)
        hard_txt = Config.FONT_UI_MED.render(self.get_text("ai_hard"), True, Config.BTN_TEXT)
        back_txt = Config.FONT_UI_MED.render(self.get_text("menu_back"), True, Config.BTN_TEXT)
        for txt, rect in [(easy_txt, self.easy_ai_rect), (hard_txt, self.hard_ai_rect), (back_txt, self.back_ai_rect)]:
            self.screen.blit(txt, (rect.centerx - txt.get_width() // 2, rect.y + (btn_h - txt.get_height()) // 2))

    def draw_leaderboard(self):
        self.screen.fill(Config.BG_COLOR)
        title = Config.FONT_UI_MSG.render(self.get_text("leaderboard_title"), True, Config.GRID_LINE)
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 20))
        top_scores = self.leaderboard.scores
        if not top_scores:
            no_score_txt = Config.FONT_UI_MED.render(self.get_text("no_scores"), True, Config.MSG_COLOR)
            self.screen.blit(no_score_txt, (Config.WIDTH // 2 - no_score_txt.get_width() // 2, 150))
        else:
            y = 80
            header_font = Config.FONT_UI_SMALL
            headers = [self.get_text("rank"), self.get_text("name"), self.get_text("total"), self.get_text("mode"), self.get_text("date")]
            x_positions = [20, 70, 190, 270, 370]
            for i, header in enumerate(headers):
                txt = header_font.render(header, True, Config.GRID_LINE)
                self.screen.blit(txt, (x_positions[i], y))
            pygame.draw.line(self.screen, Config.WOOD_BORDER, (15, y + 25), (Config.WIDTH - 15, y + 25), 2)
            y = 115
            for idx, score in enumerate(top_scores):
                rank = f"#{idx + 1}"
                name = score["name"][:12]
                total = f"{score['total']}"
                mode = score["mode"]
                date = score["date"].split()[0]
                data = [rank, name, total, mode, date]
                if idx < 3:
                    bg_rect = pygame.Rect(15, y - 5, Config.WIDTH - 30, 25)
                    pygame.draw.rect(self.screen, Config.SCORE_BG, bg_rect)
                for i, text in enumerate(data):
                    txt = Config.FONT_UI_SMALL.render(str(text), True, Config.BTN_TEXT)
                    self.screen.blit(txt, (x_positions[i], y))
                y += 30
        btn_w, btn_h = 200, 50
        self.back_leaderboard_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, Config.HEIGHT - 70, btn_w, btn_h)
        pygame.draw.rect(self.screen, Config.BTN_BG, self.back_leaderboard_rect)
        back_txt = Config.FONT_UI_MED.render(self.get_text("back"), True, Config.BTN_TEXT)
        self.screen.blit(back_txt, (self.back_leaderboard_rect.centerx - back_txt.get_width() // 2, self.back_leaderboard_rect.centery - back_txt.get_height() // 2))

    def draw_tutorial(self):
        self.screen.fill(Config.TUTORIAL_BG)
        title = Config.FONT_UI_MSG.render(self.get_text("tutorial_title"), True, Config.GRID_LINE)
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 15))
        y = 65
        sections = [("tut_1", "tut_1_desc"), ("tut_2", "tut_2_desc"), ("tut_3", "tut_3_desc"), ("tut_chat", "tut_chat_desc"), ("tut_4", "tut_4_desc")]
        for title_key, desc_key in sections:
            title_txt = Config.FONT_UI_MED.render(self.get_text(title_key), True, Config.MSG_COLOR)
            self.screen.blit(title_txt, (20, y))
            y += 25
            desc = self.get_text(desc_key)
            lines = desc.split('\n')
            for line in lines:
                line_txt = Config.FONT_UI_SMALL.render(line, True, Config.TUTORIAL_TEXT)
                self.screen.blit(line_txt, (30, y))
                y += 20
            y += 10
        btn_w, btn_h = 200, 50
        self.back_tutorial_rect = pygame.Rect(Config.WIDTH // 2 - btn_w // 2, Config.HEIGHT - 70, btn_w, btn_h)
        pygame.draw.rect(self.screen, Config.BTN_BG, self.back_tutorial_rect)
        back_txt = Config.FONT_UI_MED.render(self.get_text("back"), True, Config.BTN_TEXT)
        self.screen.blit(back_txt, (self.back_tutorial_rect.centerx - back_txt.get_width() // 2, self.back_tutorial_rect.centery - back_txt.get_height() // 2))

    def draw_chat(self):
        if self.typing_chat:
            input_rect = pygame.Rect(10, Config.HEIGHT - 35, 300, 30)
            pygame.draw.rect(self.screen, (255, 255, 255), input_rect)
            pygame.draw.rect(self.screen, Config.X_COLOR, input_rect, 2)

            txt_display = self.chat_input
            if pygame.time.get_ticks() % 1000 < 500:
                txt_display += "|"

            txt_surf = Config.FONT_CHAT.render(txt_display, True, Config.CHAT_TEXT)
            self.screen.blit(txt_surf, (input_rect.x + 5, input_rect.y + 5))

        if self.chat_history:
            start_y = Config.HEIGHT - Config.BOTTOM_BAR - 20
            current_time = pygame.time.get_ticks()

            count = 0
            for item in reversed(self.chat_history):
                if count >= 5:
                    break

                if current_time - item['time'] > self.chat_timeout:
                    continue

                msg = item['text']
                color = (0, 0, 100) if "Bạn" in msg else (100, 0, 0)
                txt_surf = Config.FONT_CHAT.render(msg, True, color)

                bg_rect = txt_surf.get_rect(bottomleft=(10, start_y))
                bg_rect.inflate_ip(10, 4)

                s = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
                s.fill((255, 255, 255, 180))
                self.screen.blit(s, bg_rect.topleft)

                self.screen.blit(txt_surf, (bg_rect.x + 5, bg_rect.y + 2))
                start_y -= 25
                count += 1

    def draw_rematch_incoming_overlay(self):
        if not self.rematch_incoming:
            return
        overlay = pygame.Surface((Config.WIDTH, Config.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        box_w, box_h = 400, 180
        box_x = (Config.WIDTH - box_w) // 2
        box_y = (Config.HEIGHT - box_h) // 2
        pygame.draw.rect(self.screen, (255, 140, 0), (box_x, box_y, box_w, box_h))
        pygame.draw.rect(self.screen, Config.WOOD_BORDER, (box_x, box_y, box_w, box_h), 3)

        seconds = max(0, self.rematch_timer_ms // 1000)
        msg = self.get_text("rematch_request").format(name=self.rematch_requester if self.rematch_requester else self.opp_name)
        txt = Config.FONT_UI_MED.render(msg, True, (255, 255, 255))
        sub_txt_str = self.get_text("rematch_accept").format(sec=seconds)
        sub_txt = Config.FONT_UI_SMALL.render(sub_txt_str, True, (255, 255, 255))
        self.screen.blit(txt, (box_x + box_w//2 - txt.get_width()//2, box_y + 30))
        self.screen.blit(sub_txt, (box_x + box_w//2 - sub_txt.get_width()//2, box_y + 90))

    def draw_draw_offer_overlay(self):
        if not self.draw_offer_incoming:
            return
        overlay = pygame.Surface((Config.WIDTH, Config.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        box_w, box_h = 420, 180
        box_x = (Config.WIDTH - box_w) // 2
        box_y = (Config.HEIGHT - box_h) // 2
        pygame.draw.rect(self.screen, (200, 80, 120), (box_x, box_y, box_w, box_h))
        pygame.draw.rect(self.screen, Config.WOOD_BORDER, (box_x, box_y, box_w, box_h), 3)

        seconds = max(0, self.draw_offer_timer_ms // 1000)
        msg = self.get_text("draw_offer").format(name=self.draw_offer_requester if self.draw_offer_requester else self.opp_name)
        txt = Config.FONT_UI_MED.render(msg, True, (255, 255, 255))
        sub_txt_str = self.get_text("draw_offer_accept").format(sec=seconds)
        sub_txt = Config.FONT_UI_SMALL.render(sub_txt_str, True, (255, 255, 255))
        self.screen.blit(txt, (box_x + box_w//2 - txt.get_width()//2, box_y + 30))
        self.screen.blit(sub_txt, (box_x + box_w//2 - sub_txt.get_width()//2, box_y + 90))

    def draw_control(self):
        bar_y = Config.BOARD_SIZE * Config.CELL_SIZE
        bar_rect = pygame.Rect(0, bar_y, Config.WIDTH, Config.BOTTOM_BAR)
        pygame.draw.rect(self.screen, Config.BG_COLOR, bar_rect)
        pygame.draw.rect(self.screen, Config.WOOD_BORDER, (0, bar_y, Config.WIDTH, 2))
        btn_w, btn_h = 100, 40
        gap = 10
        total_w = 3 * btn_w + 2 * gap + btn_w  # include space for restart if shown
        start_x = (Config.WIDTH - total_w) // 2
        btn_y = bar_y + 70

        self.menuback_rect = pygame.Rect(start_x, btn_y, btn_w, btn_h)
        self.undo_rect = pygame.Rect(start_x + btn_w + gap, btn_y, btn_w, btn_h)
        self.music_rect = pygame.Rect(start_x + 2*btn_w + 2*gap, btn_y, btn_w, btn_h)

        music_txt = "Music: On" if self.music_on else "Music: Off"
        if self.lang == "vi":
            music_txt = "Nhạc: Bật" if self.music_on else "Nhạc: Tắt"

        undo_disabled = self.game_over or not self.move_history or self.online_mode

        buttons = [
            (self.menuback_rect, "menu_back", False),
            (self.undo_rect, "undo", undo_disabled),
            (self.music_rect, music_txt, False)
        ]

        for rect, key, disabled in buttons:
            color = (180, 160, 140) if disabled else Config.BTN_BG
            pygame.draw.rect(self.screen, color, rect)
            txt_str = key if key == music_txt else self.get_text(key)
            txt = Config.FONT_UI_SMALL.render(txt_str, True, Config.BTN_TEXT)
            self.screen.blit(txt, (rect.centerx - txt.get_width() // 2, rect.centery - txt.get_height() // 2))

        # Restart only when NOT online
        if not self.online_mode:
            self.restart_rect = pygame.Rect(start_x + 3*btn_w + 3*gap, btn_y, btn_w, btn_h)
            pygame.draw.rect(self.screen, Config.BTN_BG, self.restart_rect)
            txt = Config.FONT_UI_SMALL.render(self.get_text("restart"), True, Config.BTN_TEXT)
            self.screen.blit(txt, (self.restart_rect.centerx - txt.get_width() // 2, self.restart_rect.centery - txt.get_height() // 2))
        else:
            # create a dummy rect so clicks don't crash
            self.restart_rect = pygame.Rect(0, 0, 1, 1)

        # Offer draw button: appears throughout the game screen
        self.offer_draw_rect = pygame.Rect(Config.WIDTH - 130, bar_y + 20, 110, 36)
        offer_txt = "Xin hàng" if self.lang == "vi" else "Offer Draw"
        # change color if waiting
        if self.draw_offer_sent:
            color = (180, 180, 120)
        else:
            color = Config.BTN_BG
        pygame.draw.rect(self.screen, color, self.offer_draw_rect)
        pygame.draw.rect(self.screen, Config.WOOD_BORDER, self.offer_draw_rect, 2)
        o_txt = Config.FONT_UI_SMALL.render(offer_txt, True, Config.BTN_TEXT)
        self.screen.blit(o_txt, (self.offer_draw_rect.centerx - o_txt.get_width() // 2, self.offer_draw_rect.centery - o_txt.get_height() // 2))

        msg_y = bar_y + 10
        name_x = self.my_name if (self.online_mode and self.online_role == "X") else (self.opp_name if self.online_mode else "X")
        name_o = self.my_name if (self.online_mode and self.online_role == "O") else (self.opp_name if self.online_mode else "O")

        score_str = f"{name_x}: {self.scores['X']}  |  {name_o}: {self.scores['O']}"
        score_surf = Config.FONT_UI_MED.render(score_str, True, Config.BTN_TEXT)
        score_bg_rect = score_surf.get_rect(topleft=(20, msg_y))
        pygame.draw.rect(self.screen, Config.SCORE_BG, score_bg_rect.inflate(10, 6))
        self.screen.blit(score_surf, score_bg_rect)

        if self.online_mode:
            role_txt = f"{self.get_text('you_are')} {self.online_role} ({self.my_name})"
            role_surf = Config.FONT_UI_SMALL.render(role_txt, True, Config.MSG_COLOR)
            self.screen.blit(role_surf, (Config.WIDTH - role_surf.get_width() - 20, msg_y))

        if not self.game_over:
            turn_msg = f"{self.get_text('turn_of')} {self.player}"
            if self.typing_chat:
                turn_msg = "CHAT..."
            msg_surf = Config.FONT_UI_MED.render(turn_msg, True, Config.MSG_COLOR)
        else:
            # Show rematch button in LAN: only loser can request rematch
            if self.online_mode:
                loser_role = "X" if self.winner == "O" else "O"
                if self.online_role == loser_role and not self.rematch_request_sent and not self.rematch_incoming:
                    btn_w2, btn_h2 = 180, 40
                    self.rematch_btn_rect = pygame.Rect(Config.WIDTH - btn_w2 - 20, bar_y + 70, btn_w2, btn_h2)
                    pygame.draw.rect(self.screen, (50, 200, 50), self.rematch_btn_rect)
                    pygame.draw.rect(self.screen, Config.WOOD_BORDER, self.rematch_btn_rect, 2)
                    txt = Config.FONT_UI_SMALL.render(self.get_text("rematch_btn"), True, (255, 255, 255))
                    self.screen.blit(txt, (self.rematch_btn_rect.centerx - txt.get_width()//2, self.rematch_btn_rect.centery - txt.get_height()//2))
                else:
                    # dummy rect
                    self.rematch_btn_rect = pygame.Rect(0, 0, 1, 1)
            else:
                # local (non-online) rematch behavior (unchanged)
                if not self.waiting_for_response:
                    btn_w2, btn_h2 = 180, 40
                    self.rematch_btn_rect = pygame.Rect(Config.WIDTH - btn_w2 - 20, bar_y + 70, btn_w2, btn_h2)
                    pygame.draw.rect(self.screen, (50, 200, 50), self.rematch_btn_rect)
                    pygame.draw.rect(self.screen, Config.WOOD_BORDER, self.rematch_btn_rect, 2)
                    txt = Config.FONT_UI_SMALL.render(self.get_text("rematch_btn"), True, (255, 255, 255))
                    self.screen.blit(txt, (self.rematch_btn_rect.centerx - txt.get_width()//2, self.rematch_btn_rect.centery - txt.get_height()//2))

            if self.final_trash_talk:
                msg = self.final_trash_talk if self.winner else self.get_text("draw")
            else:
                if self.winner:
                    self.final_trash_talk = self.get_trash_talk_message()
                    msg = self.final_trash_talk
                else:
                    msg = self.get_text("draw")
            msg_surf = Config.FONT_UI_MSG.render(msg, True, Config.MSG_COLOR)
            self.screen.blit(msg_surf, (Config.WIDTH // 2 - msg_surf.get_width() // 2, msg_y))

        # show waiting_for_response if set (for rematch sender)
        if self.waiting_for_response:
            wait_txt = Config.FONT_UI_SMALL.render(self.get_text("waiting_response"), True, Config.O_COLOR)
            self.screen.blit(wait_txt, (Config.WIDTH - wait_txt.get_width() - 20, bar_y + 80))

        if self.show_save_prompt:
            self.draw_save_prompt()
        if self.online_mode:
            self.draw_chat()

    def draw_save_prompt(self):
        overlay = pygame.Surface((Config.WIDTH, Config.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        box_w, box_h = 350, 150
        box_x = (Config.WIDTH - box_w) // 2
        box_y = (Config.HEIGHT - box_h) // 2
        pygame.draw.rect(self.screen, Config.TUTORIAL_BG, (box_x, box_y, box_w, box_h))
        pygame.draw.rect(self.screen, Config.WOOD_BORDER, (box_x, box_y, box_w, box_h), 3)
        prompt_txt = Config.FONT_UI_MED.render(self.get_text("save_score_prompt"), True, Config.BTN_TEXT)
        self.screen.blit(prompt_txt, (box_x + box_w // 2 - prompt_txt.get_width() // 2, box_y + 20))
        input_box = pygame.Rect(box_x + 25, box_y + 60, box_w - 50, 35)
        pygame.draw.rect(self.screen, (255, 255, 255), input_box)
        pygame.draw.rect(self.screen, Config.WOOD_BORDER, input_box, 2)
        input_txt = Config.FONT_UI_MED.render(self.player_name_input, True, Config.BTN_TEXT)
        self.screen.blit(input_txt, (input_box.x + 5, input_box.y + 5))
        hint = Config.FONT_UI_SMALL.render("Enter: Save | Esc: Cancel", True, Config.BTN_TEXT)
        self.screen.blit(hint, (box_x + box_w // 2 - hint.get_width() // 2, box_y + 110))

    # Achievements helper list
    def _ach_list(self):
        """Return the ordered achievement list used by the achievements screen."""
        ach_list = []
        for thr, aid in WIN_AI_THRESHOLDS:
            ach_list.append((aid, ACH_DEFS[aid]))
        for key in ["first_peace_request", "peace_accepted", "peace_rejected", "rematch_after_lose"]:
            ach_list.append((key, ACH_DEFS[key]))
        return ach_list

    # Draw achievements menu with scroll support
    def draw_achievements_menu(self):
        self.screen.fill((24, 24, 28))
        title_text = "THÀNH TỰU" if self.lang == "vi" else "ACHIEVEMENTS"
        title = Config.FONT_UI_MSG.render(title_text, True, (255, 255, 255))
        self.screen.blit(title, (Config.WIDTH // 2 - title.get_width() // 2, 20))

        # back button
        back_rect = pygame.Rect(20, Config.HEIGHT - 70, 200, 50)
        pygame.draw.rect(self.screen, Config.BTN_BG, back_rect)
        back_txt = Config.FONT_UI_MED.render(self.get_text("back"), True, Config.BTN_TEXT)
        self.screen.blit(back_txt, (back_rect.centerx - back_txt.get_width() // 2, back_rect.centery - back_txt.get_height() // 2))

        # compute area & content
        top_y = self.ach_view_top
        bottom_limit = Config.HEIGHT - self.ach_view_bottom_margin
        available_h = bottom_limit - top_y

        ach_list = self._ach_list()
        item_h = self.ach_item_height
        content_h = len(ach_list) * item_h
        max_scroll = max(0, content_h - available_h)

        # clamp scroll
        if self.ach_scroll < 0:
            self.ach_scroll = 0
        if self.ach_scroll > max_scroll:
            self.ach_scroll = max_scroll

        # draw a subtle clipping surface so off-screen items are hidden (optional but clean)
        clip_surface = pygame.Surface((Config.WIDTH, available_h), pygame.SRCALPHA)
        clip_surface.fill((0, 0, 0, 0))
        y = -self.ach_scroll  # start offset inside clip_surface

        padding_x = 80

        for idx, (aid, meta) in enumerate(ach_list):
            unlocked = False
            if aid.startswith("win_ai_"):
                thr = int(aid.split("_")[-1])
                if self.achievements.get("win_ai_hard", 0) >= thr:
                    unlocked = True
            else:
                if aid == "first_peace_request":
                    unlocked = self.achievements.get("first_challenge", False)
                else:
                    unlocked = self.achievements.get(aid, False)

            name = meta["name"].get(self.lang, meta["name"]["en"])
            icon = "[ACH]" if unlocked else "[LOCK]"
            color = (255, 215, 0) if unlocked and meta.get("legendary", False) else ((255,255,255) if unlocked else (120,120,120))

            # draw only if inside visible region (clip_surface coordinates)
            if y + item_h > 0 and y < available_h:
                name_surf = Config.FONT_UI_MED.render(f"{icon} {name}", True, color)
                clip_surface.blit(name_surf, (padding_x, y))

                if unlocked:
                    if aid.startswith("win_ai_"):
                        thr = int(aid.split("_")[-1])
                        reason = {"vi": f"Đã thắng AI Hard {thr} lần", "en": f"Beat AI Hard {thr} times"}[self.lang]
                    elif aid == "first_peace_request":
                        reason = {"vi": "Gửi yêu cầu hòa lần đầu", "en": "Sent draw offer (first time)"}[self.lang]
                    elif aid == "peace_accepted":
                        reason = {"vi": "Thỏa thuận hòa thành công", "en": "Draw accepted"}[self.lang]
                    elif aid == "peace_rejected":
                        reason = {"vi": "Bị từ chối hòa", "en": "Draw offer rejected"}[self.lang]
                    elif aid == "rematch_after_lose":
                        reason = {"vi": "Gửi yêu cầu tái đấu sau khi thua", "en": "Requested rematch after losing"}[self.lang]
                    else:
                        reason = ""
                else:
                    reason = "Đã Khóa" if self.lang == "vi" else "Locked"

                reason_surf = Config.FONT_UI_SMALL.render(reason, True, (200,200,200) if unlocked else (100,100,100))
                clip_surface.blit(reason_surf, (padding_x + 10, y + 34))

            y += item_h

        # blit clipped content to main screen at top_y
        self.screen.blit(clip_surface, (0, top_y))

        # draw scrollbar on right if needed
        sb_x = Config.WIDTH - 36
        sb_w = 16
        sb_rect = pygame.Rect(sb_x, top_y, sb_w, available_h)
        # background rail
        pygame.draw.rect(self.screen, (40,40,40), sb_rect, border_radius=8)

        if content_h > available_h:
            thumb_h = max(30, int(available_h * (available_h / content_h)))
            # avoid division by zero
            if max_scroll > 0:
                thumb_y = top_y + int((self.ach_scroll / max_scroll) * (available_h - thumb_h))
            else:
                thumb_y = top_y
            thumb_rect = pygame.Rect(sb_x + 2, thumb_y, sb_w - 4, thumb_h)
            pygame.draw.rect(self.screen, (200,200,200), thumb_rect, border_radius=6)
        else:
            # full thumb (no scrolling)
            thumb_rect = pygame.Rect(sb_x + 2, top_y, sb_w - 4, available_h)
            pygame.draw.rect(self.screen, (120,120,120), thumb_rect, border_radius=6)

        # store scrollbar geometry so event handling can use it (optional)
        self._ach_scrollbar_rect = sb_rect
        self._ach_max_scroll = max_scroll
        self._ach_available_h = available_h
        self._ach_content_h = content_h

    def handle_place_move(self, row, col, is_remote=False):
        if not (0 <= row < self.board.size and 0 <= col < self.board.size) or self.board.grid[row][col] != "":
            return
        if self.online_mode and not is_remote:
            if self.player != self.online_role:
                return

        self.board.grid[row][col] = self.player
        self.move_history.append((row, col))
        self.board.place_animations[(row, col)] = (pygame.time.get_ticks(), 250)
        self.play_click()

        if self.online_mode and not is_remote:
            try:
                self.network.send_move(row, col)
            except:
                pass

        self.winner = self.board.check_winner()
        if self.winner or all(self.board.grid[r][c] != "" for r in range(self.board.size) for c in range(self.board.size)):
            self.game_over = True
            self.play_end_sound()
            if self.winner:
                self.flash_phase = 1
                self.last_flash_time = pygame.time.get_ticks()
                self.scores[self.winner] += 1
                self.create_win_particles()
                self.trigger_screen_shake(15)

                # Achievement: if beat AI hard (local game)
                if self.ai_enabled and self.ai_level == "hard" and not self.online_mode:
                    # CHỈ tích lũy khi PLAYER (X) thắng AI (O)
                    if self.winner == "X":  # Player luôn là X, AI luôn là O
                        self.achievements["win_ai_hard"] = self.achievements.get("win_ai_hard", 0) + 1
                        count = self.achievements["win_ai_hard"]
                        # check thresholds
                        for thr, aid in WIN_AI_THRESHOLDS:
                            if count == thr:
                                title = ACH_DEFS[aid]["name"].get(self.lang, ACH_DEFS[aid]["name"]["en"])
                                reason_templates = {
                                    "vi": f"thắng AI Hard {thr} lần",
                                    "en": f"beat AI Hard {thr} times"
                                }
                                legendary = ACH_DEFS[aid]["legendary"]
                                self.show_achievement_popup(title, reason_templates[self.lang], legendary)
                                break
                        save_achievements(self.achievements)

            if not self.online_mode:
                if self.cached_player_name:
                    self.player_name_input = self.cached_player_name
                    self.save_score_to_leaderboard()
                    self.show_save_prompt = False
                else:
                    self.show_save_prompt = True
        else:
            self.player = "O" if self.player == "X" else "X"

    def handle_ai_move(self):
        if self.ai_enabled and not self.game_over and self.player == "O" and self.ai:
            pygame.time.delay(150)
            mv = self.ai.get_move()
            if mv:
                self.handle_place_move(mv[0], mv[1])

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            # If quitting during LAN game -> notify opponent and (only if it's our turn) apply penalty
            if self.online_mode and not self.game_over:
                try:
                    # treat quitting as intentional: notify opponent so they won't be penalized
                    self.intentional_quit = True
                    self.network.send_opponent_quit(self.my_name)
                except:
                    pass
                # apply local ban for intentional quit
                self.apply_ban(60, name=self.my_name)
            return False

        # ACHIEVEMENTS: mouse wheel & scrollbar drag support
        if self.state == "achievements":
            # MOUSEWHEEL (pygame 2)
            if event.type == pygame.MOUSEWHEEL:
                # event.y is +ve when scrolling up
                self.ach_scroll -= int(event.y * 30)
                # clamp
                if hasattr(self, '_ach_max_scroll'):
                    self.ach_scroll = max(0, min(self.ach_scroll, self._ach_max_scroll))
                return True

            # older style wheel events (button 4/5) and start dragging
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 4:  # wheel up
                    self.ach_scroll -= 30
                    if hasattr(self, '_ach_max_scroll'):
                        self.ach_scroll = max(0, min(self.ach_scroll, self._ach_max_scroll))
                    return True
                elif event.button == 5:  # wheel down
                    self.ach_scroll += 30
                    if hasattr(self, '_ach_max_scroll'):
                        self.ach_scroll = max(0, min(self.ach_scroll, self._ach_max_scroll))
                    return True
                elif event.button == 1:
                    # start dragging if click on scrollbar rail
                    mx, my = event.pos
                    # compute scrollbar area (must match draw)
                    top = self.ach_view_top
                    bottom = Config.HEIGHT - self.ach_view_bottom_margin
                    avail_h = bottom - top
                    sb_x = Config.WIDTH - 36
                    sb_rect = pygame.Rect(sb_x, top, 16, avail_h)
                    # compute content height & max_scroll
                    content_h = len(self._ach_list()) * self.ach_item_height
                    max_scroll = max(0, content_h - avail_h)
                    if sb_rect.collidepoint(mx, my) and content_h > avail_h:
                        self.ach_dragging = True
                        self.ach_drag_start_y = my
                        self.ach_drag_start_scroll = self.ach_scroll
                        return True

            if event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1 and self.ach_dragging:
                    self.ach_dragging = False
                    return True

            if event.type == pygame.MOUSEMOTION and self.ach_dragging:
                # update scroll based on drag delta
                mx, my = event.pos
                top = self.ach_view_top
                bottom = Config.HEIGHT - self.ach_view_bottom_margin
                avail_h = bottom - top
                content_h = len(self._ach_list()) * self.ach_item_height
                max_scroll = max(0, content_h - avail_h)
                dy = my - self.ach_drag_start_y
                if max_scroll > 0 and avail_h > 0:
                    # map dy -> scroll proportionally to available height
                    new_scroll = self.ach_drag_start_scroll + int((dy / float(avail_h)) * max_scroll)
                else:
                    new_scroll = 0
                # clamp
                self.ach_scroll = max(0, min(new_scroll, max_scroll))
                return True

        # REMATCH INCOMING handling
        if self.rematch_incoming:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    # accept rematch
                    try:
                        if self.online_mode:
                            self.network.send_rematch_accept()
                            # swap roles for balance: X -> O, O -> X
                            if self.online_role:
                                self.online_role = 'O' if self.online_role == 'X' else 'X'
                        # start new round (winner accepted)
                        self.reset_game(ai_mode=False, online_mode=self.online_mode)
                    except:
                        pass
                    self.rematch_incoming = False
                    self.rematch_timer_ms = 0
                    self.rematch_requester = None
                elif event.key == pygame.K_ESCAPE:
                    try:
                        if self.online_mode:
                            self.network.send_rematch_deny()
                    except:
                        pass
                    self.rematch_incoming = False
                    self.rematch_timer_ms = 0
                    self.rematch_requester = None
            return True

        # DRAW OFFER INCOMING handling
        if self.draw_offer_incoming:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    # accept draw
                    try:
                        if self.online_mode:
                            self.network.send_accept_draw()
                    except:
                        pass
                    self.game_over = True
                    self.winner = None
                    self.final_trash_talk = ""
                    self.center_message = self.get_text("draw_agreed")
                    self.center_message_time = 3000
                    # achievement: both acceptor and sender should get peace_accepted
                    if not self.achievements.get("peace_accepted", False):
                        self.achievements["peace_accepted"] = True
                        save_achievements(self.achievements)
                        title = ACH_DEFS["peace_accepted"]["name"].get(self.lang, ACH_DEFS["peace_accepted"]["name"]["en"])
                        reason = {"vi": "đồng ý hòa", "en": "accepted a draw"}[self.lang]
                        self.show_achievement_popup(title, reason, ACH_DEFS["peace_accepted"]["legendary"])
                    self.draw_offer_incoming = False
                    self.draw_offer_timer_ms = 0
                    self.draw_offer_requester = None
                elif event.key == pygame.K_ESCAPE:
                    try:
                        if self.online_mode:
                            self.network.send_deny_draw()
                    except:
                        pass
                    self.draw_offer_incoming = False
                    self.draw_offer_timer_ms = 0
                    self.draw_offer_requester = None
            return True

        # Chat Input
        if self.online_mode and self.state == "game":
            if self.typing_chat:
                if event.type == pygame.TEXTINPUT:
                    if len(self.chat_input) < 40:
                        self.chat_input += event.text
                    return True

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        if self.chat_input.strip():
                            msg = self.chat_input
                            try:
                                self.network.send_chat(msg)
                            except:
                                pass
                            self.chat_history.append({
                                'text': f"Bạn: {msg}",
                                'time': pygame.time.get_ticks()
                            })
                            self.chat_input = ""
                        self.typing_chat = False
                        pygame.key.stop_text_input()
                    elif event.key == pygame.K_ESCAPE:
                        self.typing_chat = False
                        pygame.key.stop_text_input()
                    elif event.key == pygame.K_BACKSPACE:
                        self.chat_input = self.chat_input[:-1]
                return True
            else:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                    self.typing_chat = True
                    pygame.key.start_text_input()
                    return True

        # Input IP
        if self.state == "input_ip":
            if event.type == pygame.TEXTINPUT:
                if len(self.input_ip) < 15:
                    self.input_ip += event.text
                return True
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    if self.network.connect_to_server(self.input_ip):
                        self.online_role = "O"
                        try:
                            self.network.send_name(self.my_name)
                        except:
                            pass
                        self.state = "waiting"
                    else:
                        self.error_msg = self.get_text("connect_fail")
                elif event.key == pygame.K_BACKSPACE:
                    self.input_ip = self.input_ip[:-1]
                elif event.key == pygame.K_ESCAPE:
                    self.go_to_online_select()
            return True

        # Input Name (LAN)
        if self.state == "input_name_lan":
            if event.type == pygame.TEXTINPUT:
                if len(self.input_name_lan_str) < 12:
                    self.input_name_lan_str += event.text
                return True
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    if self.input_name_lan_str.strip():
                        self.my_name = self.input_name_lan_str.strip()

                        # AFTER entering name, do a smart local IP check and warn user if it looks like WARP/VPN is active.
                        ip = self.network.get_local_ip()
                        # use internal private IP test to decide
                        if not self.network._is_private_ip(ip):
                            try:
                                self.center_message = "⚠️ Tắt WARP / VPN để chơi LAN"
                                self.center_message_time = 5000
                            except:
                                pass

                        self.go_to_online_select()
                elif event.key == pygame.K_BACKSPACE:
                    self.input_name_lan_str = self.input_name_lan_str[:-1]
                elif event.key == pygame.K_ESCAPE:
                    self.go_to_menu()
            return True

        if self.state == "waiting":
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.network.close()
                self.go_to_online_select()
            return True

        if self.show_save_prompt:
            if event.type == pygame.TEXTINPUT:
                if len(self.player_name_input) < 15:
                    self.player_name_input += event.text
                return True
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.save_score_to_leaderboard()
                elif event.key == pygame.K_ESCAPE:
                    self.show_save_prompt = False
                    self.player_name_input = ""
                elif event.key == pygame.K_BACKSPACE:
                    self.player_name_input = self.player_name_input[:-1]
                return True

        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos

            if self.state == "menu":
                # trophy click -> achievements menu
                if Game.TROPHY_RECT.collidepoint(mx, my):
                    self.state = "achievements"
                    return True

                if self.play_rect.collidepoint(mx, my):
                    self.reset_game(ai_mode=False)
                elif self.ai_select_rect.collidepoint(mx, my):
                    self.go_to_ai_select()
                elif self.online_btn_rect.collidepoint(mx, my):
                    remain = self.is_lan_cooldown_active()
                    if remain:
                        self.error_msg = self.get_text("cooldown_wait").format(sec=remain)
                    else:
                        self.state = "input_name_lan"
                        self.input_name_lan_str = ""
                elif self.leaderboard_rect.collidepoint(mx, my):
                    self.go_to_leaderboard()
                elif self.tutorial_rect.collidepoint(mx, my):
                    self.go_to_tutorial()
                elif self.lang_rect.collidepoint(mx, my):
                    self.lang = "en" if self.lang == "vi" else "vi"
                elif self.quit_rect.collidepoint(mx, my):
                    return False

            elif self.state == "achievements":
                # back button area: top-left small rect
                back_rect = pygame.Rect(20, Config.HEIGHT - 70, 200, 50)
                if back_rect.collidepoint(mx, my):
                    self.go_to_menu()

            elif self.state == "online_select":
                if self.host_rect.collidepoint(mx, my):
                    remain = self.is_lan_cooldown_active()
                    if remain:
                        self.error_msg = self.get_text("cooldown_wait").format(sec=remain)
                    else:
                        if self.network.start_server():
                            self.online_role = "X"
                            self.scores = {"X": 0, "O": 0}
                            self.state = "waiting"
                elif self.join_rect.collidepoint(mx, my):
                    remain = self.is_lan_cooldown_active()
                    if remain:
                        self.error_msg = self.get_text("cooldown_wait").format(sec=remain)
                    else:
                        self.state = "input_ip"
                        self.input_ip = ""
                        self.error_msg = ""
                elif self.back_online_rect.collidepoint(mx, my):
                    self.go_to_menu()

            elif self.state == "ai_select":
                if self.easy_ai_rect.collidepoint(mx, my):
                    self.ai_level = "easy"
                    self.reset_game(ai_mode=True)
                elif self.hard_ai_rect.collidepoint(mx, my):
                    self.ai_level = "hard"
                    self.reset_game(ai_mode=True)
                elif self.back_ai_rect.collidepoint(mx, my):
                    self.go_to_menu()

            elif self.state == "leaderboard":
                if self.back_leaderboard_rect.collidepoint(mx, my):
                    self.go_to_menu()

            elif self.state == "tutorial":
                if self.back_tutorial_rect.collidepoint(mx, my):
                    self.go_to_menu()

            elif self.state == "game":
                if self.show_save_prompt:
                    pass
                elif self.restart_rect.collidepoint(mx, my):
                    if self.online_mode:
                        # disabled for LAN
                        self.play_click()
                    else:
                        self.reset_game(self.ai_enabled)
                elif self.menuback_rect.collidepoint(mx, my):
                    # Distinguish intentional quit vs sudden disconnect:
                    if self.online_mode and not self.game_over:
                        try:
                            self.intentional_quit = True
                            self.network.send_opponent_quit(self.my_name)
                        except:
                            pass
                        # apply local ban (intentional leave)
                        self.apply_ban(60, name=self.my_name)
                        self.go_to_menu()
                    else:
                        self.go_to_menu()
                elif self.music_rect.collidepoint(mx, my):
                    self.toggle_music()
                elif self.undo_rect.collidepoint(mx, my):
                    self.undo_move()
                elif self.game_over and self.rematch_btn_rect.collidepoint(mx, my):
                    # rematch request (loser presses)
                    if self.online_mode:
                        self.request_rematch()
                    else:
                        # local rematch: just reset
                        self.reset_game(ai_mode=self.ai_enabled)
                elif self.offer_draw_rect.collidepoint(mx, my):
                    # Offer draw action (xin hàng)
                    if self.online_mode:
                        if not self.draw_offer_sent:
                            try:
                                # Achievement: first peace request (we map to 'first_challenge')
                                if not self.achievements.get("first_challenge", False):
                                    self.achievements["first_challenge"] = True
                                    save_achievements(self.achievements)
                                    title = ACH_DEFS["first_peace_request"]["name"].get(self.lang, ACH_DEFS["first_peace_request"]["name"]["en"])
                                    reason = {"vi": "Gửi yêu cầu hòa lần đầu", "en": "Sent draw offer (first time)"}[self.lang]
                                    self.show_achievement_popup(title, reason, ACH_DEFS["first_peace_request"]["legendary"])
                                self.network.send_offer_draw()
                                self.draw_offer_sent = True
                                self.center_message = "Draw offer sent"
                                self.center_message_time = 2000
                            except:
                                self.center_message = "Failed to send draw offer"
                                self.center_message_time = 2000
                    else:
                        # local: show incoming offer immediately (simulate remote)
                        if not self.draw_offer_incoming and not self.draw_offer_sent:
                            # treat this as first peace request if not yet
                            if not self.achievements.get("first_challenge", False):
                                self.achievements["first_challenge"] = True
                                save_achievements(self.achievements)
                                title = ACH_DEFS["first_peace_request"]["name"].get(self.lang, ACH_DEFS["first_peace_request"]["name"]["en"])
                                reason = {"vi": "Gửi yêu cầu hòa lần đầu", "en": "Sent draw offer (first time)"}[self.lang]
                                self.show_achievement_popup(title, reason, ACH_DEFS["first_peace_request"]["legendary"])
                            # self as sender -> show incoming overlay for other local player
                            self.draw_offer_incoming = True
                            self.draw_offer_timer_ms = self.DRAW_OFFER_TIMEOUT_MS
                            self.draw_offer_requester = self.my_name
                elif my < Config.BOARD_SIZE * Config.CELL_SIZE and not self.game_over:
                    if not (self.ai_enabled and self.player == "O"):
                        col = mx // Config.CELL_SIZE
                        row = my // Config.CELL_SIZE
                        self.handle_place_move(row, col)
        return True

    def update_flash(self):
        if self.flash_phase > 0:
            now = pygame.time.get_ticks()
            if now - self.last_flash_time >= self.flash_interval:
                self.flash_phase += 1
                self.last_flash_time = now
                if self.flash_phase > 6:
                    self.flash_phase = 0

    def draw_center_message(self):
        if not self.center_message:
            return
        txt = Config.FONT_UI_MSG.render(self.center_message, True, Config.MSG_COLOR)
        self.screen.blit(txt, (Config.WIDTH // 2 - txt.get_width() // 2, Config.HEIGHT // 2 - txt.get_height() // 2))

    # Achievement menu drawing
    def draw_achievements_menu_old(self):
        # kept for reference (not used)
        pass

    def run(self):
        self.start_music()
        running = True
        while running:
            # FPS cap and dt
            dt = self.clock.tick(Config.FPS)

            # process network queue for waiting/online states
            if self.state == "waiting" or self.online_mode:
                while not self.network.msg_queue.empty():
                    cmd_type, data = self.network.msg_queue.get()

                    if cmd_type == "sys" and data == "disconnect":
                        # unexpected disconnect: award local win (no penalty)
                        if self.online_mode and not self.game_over:
                            self.game_over = True
                            self.winner = self.online_role
                            self.scores[self.winner] += 1
                            self.play_end_sound()
                            self.create_win_particles()
                            self.trigger_screen_shake(12)
                            # show friendly disconnect message (no ban)
                            if data:
                                left_name = data
                            else:
                                left_name = self.opp_name
                            self.center_message = self.get_text("opponent_left").format(name=self.opp_name)
                            self.center_message_time = 5000
                        # close network and return to menu (no ban applied)
                        self.network.close()
                        self.online_mode = False
                        self.online_role = None
                        self.go_to_menu()

                    elif cmd_type == "name":
                        self.opp_name = data
                        if self.state == "waiting":
                            if self.online_role == "X":
                                try:
                                    self.network.send_name(self.my_name)
                                except:
                                    pass
                                self.reset_game(ai_mode=False, online_mode=True)
                            else:
                                self.reset_game(ai_mode=False, online_mode=True)

                    elif cmd_type == "left":
                        # legacy left message (remote intentionally closed)
                        left_name = data
                        if self.online_mode and not self.game_over:
                            self.game_over = True
                            self.winner = self.online_role
                            self.scores[self.winner] += 1
                            self.play_end_sound()
                            self.create_win_particles()
                            self.trigger_screen_shake(12)
                            self.center_message = self.get_text("opponent_left").format(name=left_name)
                            self.center_message_time = 5000
                        self.network.close()
                        self.online_mode = False
                        self.online_role = None
                        self.go_to_menu()

                    elif cmd_type == "opponent_quit":
                        # opponent intentionally quits: award local win BUT DO NOT PENALIZE RECEIVER
                        left_name = data if data else self.opp_name
                        if self.online_mode and not self.game_over:
                            self.game_over = True
                            self.winner = self.online_role
                            self.scores[self.winner] += 1
                            self.play_end_sound()
                            self.create_win_particles()
                            self.trigger_screen_shake(12)
                            # show opponent-left message
                            self.center_message = self.get_text("opponent_left").format(name=left_name)
                            self.center_message_time = 5000
                        # close connection and return to menu (no ban)
                        self.network.close()
                        self.online_mode = False
                        self.online_role = None
                        self.go_to_menu()

                    elif cmd_type == "net_restart":
                        # ignore restart packets for LAN
                        pass

                    elif cmd_type == "net_req_rematch":
                        # incoming rematch
                        if self.online_mode:
                            self.rematch_incoming = True
                            self.rematch_timer_ms = self.REMATCH_TIMEOUT_MS
                            self.rematch_requester = self.opp_name
                            # show overlay; waiting handled in event loop
                    elif cmd_type == "net_accept_rematch":
                        # opponent accepted our rematch request
                        if self.rematch_request_sent:
                            # swap roles for balance: X -> O, O -> X
                            if self.online_role:
                                self.online_role = 'O' if self.online_role == 'X' else 'X'
                            # start new round for us
                            self.reset_game(ai_mode=False, online_mode=True)
                            self.rematch_request_sent = False
                            self.waiting_for_response = False
                            self.center_message = "Rematch accepted"
                            self.center_message_time = 2000
                    elif cmd_type == "net_deny_rematch":
                        if self.rematch_request_sent:
                            self.rematch_request_sent = False
                            self.waiting_for_response = False
                            self.center_message = self.get_text("rematch_denied")
                            self.center_message_time = 3000

                    elif cmd_type == "offer_draw":
                        # incoming draw offer
                        if self.online_mode:
                            self.draw_offer_incoming = True
                            self.draw_offer_timer_ms = self.DRAW_OFFER_TIMEOUT_MS
                            self.draw_offer_requester = self.opp_name
                    elif cmd_type == "accept_draw":
                        # opponent accepted our draw offer
                        if self.draw_offer_sent:
                            self.game_over = True
                            self.winner = None
                            self.draw_offer_sent = False
                            self.center_message = self.get_text("draw_agreed")
                            self.center_message_time = 3000
                            # award peace_accepted to the original sender as well
                            if not self.achievements.get("peace_accepted", False):
                                self.achievements["peace_accepted"] = True
                                save_achievements(self.achievements)
                                title = ACH_DEFS["peace_accepted"]["name"].get(self.lang, ACH_DEFS["peace_accepted"]["name"]["en"])
                                reason = {"vi": "đồng ý hòa (đối phương chấp thuận)", "en": "draw accepted (opponent accepted)"}[self.lang]
                                self.show_achievement_popup(title, reason, ACH_DEFS["peace_accepted"]["legendary"])
                    elif cmd_type == "deny_draw":
                        if self.draw_offer_sent:
                            self.draw_offer_sent = False
                            self.center_message = self.get_text("draw_denied")
                            self.center_message_time = 3000
                            # award peace_rejected to sender (they got rejected)
                            if not self.achievements.get("peace_rejected", False):
                                self.achievements["peace_rejected"] = True
                                save_achievements(self.achievements)
                                title = ACH_DEFS["peace_rejected"]["name"].get(self.lang, ACH_DEFS["peace_rejected"]["name"]["en"])
                                reason = {"vi": "Gửi yêu cầu hòa nhưng bị từ chối", "en": "Sent draw offer but was rejected"}[self.lang]
                                self.show_achievement_popup(title, reason, ACH_DEFS["peace_rejected"]["legendary"])

                    elif self.online_mode:
                        if cmd_type == "move":
                            self.handle_place_move(data[0], data[1], is_remote=True)
                        elif cmd_type == "chat":
                            self.chat_history.append({
                                'text': f"Đối thủ: {data}",
                                'time': pygame.time.get_ticks()
                            })
                            if Config.TING_SOUND:
                                try:
                                    Config.TING_SOUND.play()
                                except:
                                    pass

            # end while msg_queue

            # handle incoming messages done

            pass

            # (Note: sudden disconnects are handled above by sys disconnect and do NOT call apply_ban)

            # ------------------------------------------------------------------

            # continue to events

            # (No further changes needed here.) 

            # ------------------------------------------------------------------

            # End network handling for this frame

            # (Flow continues below.)

            # ------------------------------------------------------------------

            # nothing more to do here for now

            # ------------------------------------------------------------------

            # (The repeated 'pass' above is just to keep the structured comments readable.) 

            # ------------------------------------------------------------------

            pass

            # (The repeated 'pass' above is just to keep the structured comments readable.) 

            # ------------------------------------------------------------------

            # continue to event loop below

            # ------------------------------------------------------------------

            for event in pygame.event.get():
                if not self.handle_event(event):
                    running = False
                    break

            if not running:
                break

            # timers for rematch incoming
            if self.rematch_incoming:
                self.rematch_timer_ms -= dt
                if self.rematch_timer_ms <= 0:
                    # auto-decline
                    try:
                        if self.online_mode:
                            self.network.send_rematch_deny()
                    except:
                        pass
                    self.rematch_incoming = False
                    self.rematch_timer_ms = 0
                    self.rematch_requester = None

            # timers for draw offer incoming
            if self.draw_offer_incoming:
                self.draw_offer_timer_ms -= dt
                if self.draw_offer_timer_ms <= 0:
                    # auto-decline
                    try:
                        if self.online_mode:
                            self.network.send_deny_draw()
                    except:
                        pass
                    self.draw_offer_incoming = False
                    self.draw_offer_timer_ms = 0
                    self.draw_offer_requester = None

            # (Optional) Could implement a timeout for outgoing rematch/draw offers, but for simplicity keep sender waiting until response or explicit deny
            # For outgoing draw offers we currently mark draw_offer_sent True until we receive response or denial.

            self.handle_ai_move()
            self.update_flash()
            self.update_particles()
            self.update_screen_shake()

            mouse_pos = pygame.mouse.get_pos()

            if self.state == "menu":
                self.draw_menu()
            elif self.state == "input_name_lan":
                self.draw_input_name_lan()
            elif self.state == "online_select":
                self.draw_online_select()
            elif self.state == "input_ip":
                self.draw_input_ip()
            elif self.state == "waiting":
                self.draw_waiting()
            elif self.state == "ai_select":
                self.draw_ai_select()
            elif self.state == "leaderboard":
                self.draw_leaderboard()
            elif self.state == "tutorial":
                self.draw_tutorial()
            elif self.state == "achievements":
                self.draw_achievements_menu()
            elif self.state == "game":
                self.board.draw(self.screen, self.state, self.player, mouse_pos)
                self.draw_control()
                self.board.draw_highlight(self.screen, self.flash_phase)
                self.draw_particles()
                # center message on top of game content
                if self.center_message:
                    self.draw_center_message()
                if self.rematch_incoming:
                    self.draw_rematch_incoming_overlay()
                if self.draw_offer_incoming:
                    self.draw_draw_offer_overlay()

            # draw achievement popup on top if present
            self.draw_achievement_popup()

            # apply shake
            final_surface = self.apply_shake_offset(self.screen.copy())
            self.screen.blit(final_surface, (0, 0))

            # update center message timer
            if self.center_message_time > 0:
                self.center_message_time -= dt
                if self.center_message_time <= 0:
                    self.center_message = ""
                    self.center_message_time = 0

            pygame.display.flip()

        # On exit make sure to notify opponent if we intentionally left during a game
        try:
            if self.intentional_quit and self.online_mode and not self.network.disconnected_midgame:
                try:
                    self.network.send_opponent_quit(self.my_name)
                except:
                    pass
        except:
            pass

        self.network.close()
        pygame.quit()
        sys.exit()

# ======================= SPLASH + MAIN =======================================
try:
    from splash import show_splash
except ImportError:
    def show_splash(screen, clock):
        pass

if __name__ == '__main__':
    if not os.path.exists("assets"):
        print("Cảnh báo: Không tìm thấy thư mục 'assets'.")

    screen = pygame.display.set_mode((Config.WIDTH, Config.HEIGHT))
    pygame.display.set_caption(Config.TEXTS['title']['vi'])
    clock = pygame.time.Clock()

    show_splash(screen, clock)
    game = Game(screen, clock)
    game.run()

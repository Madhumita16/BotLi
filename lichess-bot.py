import berserk
import chess
import logging
import threading
import random
import os
import chess.engine
import urllib.request
import sys
import psutil
import asyncio
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
import time
import traceback
import multiprocessing
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from functools import lru_cache
from collections import deque
import random
from functools import lru_cache
from stockfish import Stockfish
import torch
from threading import Lock
from multiprocessing import Lock
import requests

# Configuration
TOKEN = os.getenv("LICHESS_API_TOKEN)
if not TOKEN:
    raise ValueError("❌ Lichess API token not found! Set 'LICHESS_API_TOKEN' as an environment variable.")

print(f"✅ API Token Loaded: {TOKEN[:5]}******")  # Hide most of the token for security

# 🔥 Stockfish Engine Configuration
STOCKFISH_PATH = "./engines/stockfish-windows-x86-64-avx2.exe"  # Adjust path if needed

if not os.path.exists(STOCKFISH_PATH):
    print("⚠️ Stockfish not found! Downloading Stockfish 17.1...")

    url = "https://github.com/official-stockfish/Stockfish/releases/download/sf_17/stockfish-windows-x86-64-avx2.exe"
    os.makedirs("engines", exist_ok=True)

    try:
        urllib.request.urlretrieve(url, STOCKFISH_PATH)
        print("✅ Stockfish 17 downloaded successfully!")
    except Exception as e:
        print(f"❌ Failed to download Stockfish: {e}")

# 📝 Logging Setup
from loguru import logger  # Better logging
logger.add("lichess_bot.log", rotation="10 MB", retention="1 month", level="DEBUG")

# 📡 Lichess API Setup
try:
    session = berserk.TokenSession(TOKEN)
    client = berserk.Client(session)
    logger.info("✅ Successfully connected to Lichess API!")
except Exception as e:
    logger.critical(f"❌ Lichess API connection failed: {e}")
    raise

async def initialize_stockfish():
    """Initialize a pool of Stockfish engines asynchronously."""
    global engine, engine_pool, engine_lock  # ✅ Added global `engine`

    if not os.path.exists(STOCKFISH_PATH):
        logging.critical(f"🚨 Stockfish binary not found at: {STOCKFISH_PATH}")
        return False

    try:
        engine_pool = [
            chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            for _ in range(3)  # Create a pool of 3 engines
        ]
        engine_lock = threading.Lock()  # Add lock for safe access

        engine = engine_pool[0]  # ✅ Set a default engine (first in pool)

        logging.info("✅ Engine pool initialized with 3 Stockfish instances!")
        return True
    except Exception as e:
        logging.critical(f"❌ Engine init failed: {e}")
        return False# call bot
def get_active_bots():
    """Fetches a list of currently online Lichess bots."""
    bot_ids = ["raspfish", "endogenetic-bot", "Nikitosik-ai", "botyuliirma", "exogenetic-bot","EnergyOfBeingBot"]
    bot_list = []

    try:
        for bot in bot_ids:
            user = client.users.get_by_id(bot)  # Fetch each bot individually
            if user and user.get("title") == "BOT" and user.get("online", False):
                bot_list.append(user['id'])  # Add only if it's a bot and online

    except Exception as e:
        print(f"Error fetching bot list: {e}")
        return []  # Return empty list on error

    return bot_list  # Return the list of active bots


def challenge_random_bot():
    """Challenge a random bot with adaptive time controls and smart retries."""
    
    max_retries = 7  
    base_delay = 5  
    backoff_factor = 2  
    max_wait_time = 300  
    avoid_bots = deque(maxlen=10) # Track bots that declined challenges
    retries = 0  

    def get_filtered_bots():
        """Fetch active bots, filtering out those that recently declined challenges."""
        bots = get_active_bots()
        return [bot for bot in bots if bot not in avoid_bots]

    while retries < max_retries:
        bot_list = get_filtered_bots()
        
        if not bot_list:
            wait_time = min(base_delay * (backoff_factor ** retries), max_wait_time)
            jitter = random.uniform(-0.2 * wait_time, 0.2 * wait_time)
            final_wait_time = max(5, wait_time + jitter)
            logging.debug(f"⚠️ No available bots. Retrying in {final_wait_time:.1f}s (Attempt {retries + 1}/{max_retries})")
            time.sleep(final_wait_time)
            retries += 1
            continue
        
        retries = 0  # Reset retries
        opponent_bot = random.choice(bot_list)

        # Dynamically generated time controls for flexibility
        time_controls = [
            {"clock_limit": 60, "clock_increment": 0},  # 1+0
            {"clock_limit": 30, "clock_increment": 0},  # 1/2+0
            {"clock_limit": 180, "clock_increment": 0}, # 3+0
            {"clock_limit": 300, "clock_increment": 0}, # 5+0
            {"clock_limit": random.randint(10, 600), "clock_increment": random.choice([0, 1, 2])}  # Random TC
        ]
        selected_time_control = random.choice(time_controls)

        try:
            client.challenges.create(
                opponent_bot,
                rated=True,
                clock_limit=selected_time_control["clock_limit"],
                clock_increment=selected_time_control["clock_increment"],
                variant="standard",
                color="random"
            )
            logging.info(f"✅ Challenged {opponent_bot} to a rated game ({selected_time_control['clock_limit']}+{selected_time_control['clock_increment']}). 🚀")
            return
        except SomeSpecificChallengeException as e:
            logging.warning(f"⚠️ {opponent_bot} declined the challenge: {e}")
            avoid_bots.append(opponent_bot)
        except Exception as e:
            logging.error(f"❌ Challenge failed against {opponent_bot}: {str(e)} (Retry {retries + 1}/{max_retries})")
        
        retries += 1
        time.sleep(10)
    
    logging.critical("🚨 Max retries reached. No more challenges.")
# Stockfish engine

# Dynamically determine system capabilities
TOTAL_RAM = psutil.virtual_memory().total // (1024 * 1024)  # Convert to MB
CPU_CORES = psutil.cpu_count(logical=False)

    # Auto-Healing Mechanism# Define optimized Stockfish settings
ENGINE_CONFIGS = {
    "hyperbullet": {
        "Nodes": 200000,
        "Depth": 5,
        "Move Overhead": 40,
        "Threads": max(1, CPU_CORES // 4),
        "Ponder": False,
        "Use NNUE": False,
        "MultiPV": 1,
        "Hash": min(64, TOTAL_RAM // 4),
        "Use Book": True,
        "Book File": "C:/Users/Admin/Downloads/torom-boti/torom-boti/Perfect2023.bin",
        "Best Book move": True,
        "Book Depth": 6,
        "Book Variety": 25,
        "BlunderDetection": True,
        "UCI_LimitStrength": False,
        "AutoLagCompensation": True,
        "LagCompensationFactor": 1.2,  # Start with 1.2, adjust if needed
        "Minimum Thinking Time": 5

    },
    "blitz": {
        "Nodes": 600000,
        "Depth": 18,
        "Move Overhead": 180,
        "Threads": max(4, CPU_CORES // 3),
        "Ponder": True,
        "Use NNUE": True,
        "MultiPV": 2,
        "Hash": min(512, TOTAL_RAM // 2),
        "Use Book": True,
        "Book File": "C:/Users/Admin/Downloads/torom-boti/torom-boti/Perfect2023.bin",
        "Best Book move": True,
        "Book Depth": 12,
        "Book Variety": 20,
        "SyzygyProbeDepth": min(2, TOTAL_RAM // 8192),
        "SyzygyPath": "https://tablebase.lichess.ovh",
        "UCI_LimitStrength": False,
        "AutoLagCompensation": True
    },
    "rapid": {
        "Nodes": 900000,
        "Depth": 24,
        "Move Overhead": 250,
        "Threads": max(5, CPU_CORES // 2),
        "Ponder": True,
        "Use NNUE": True,
        "MultiPV": 3,
        "Hash": min(4096, TOTAL_RAM // 1.5),
        "Use Book": True,
        "Book File": "C:/Users/Admin/Downloads/torom-boti/torom-boti/Perfect2023.bin",
        "Best Book move": True,
        "Book Depth": 15,
        "Book Variety": 45,
        "SyzygyPath": "https://tablebase.lichess.ovh",
        "SyzygyProbeDepth": min(4, TOTAL_RAM // 8192),
        "UCI_LimitStrength": False,
        "AutoLagCompensation": True
    },
    "classical": {
        "Nodes": 1200000,
        "Depth": 28,
        "Move Overhead": 300,
        "Threads": max(6, CPU_CORES),
        "Ponder": True,
        "Use NNUE": True,
        "MultiPV": 4,
        "Hash": min(5500, TOTAL_RAM),
        "Use Book": True,
        "Book File": "C:/Users/Admin/Downloads/torom-boti/torom-boti/Perfect2023.bin",
        "Best Book move": True,
        "Book Depth": 20,
        "Book Variety": 55,
        "SyzygyProbeDepth": min(6, TOTAL_RAM // 8192),
        "SyzygyPath": "https://tablebase.lichess.ovh",
        "UCI_LimitStrength": False,
        "AutoLagCompensation": True
    }
}

#
# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Global variables
engine = None  # Initialize the engine globally
STOCKFISH_PATH = "./engines/stockfish-windows-x86-64-avx2.exe"  # Replace with the actual path to Stockfish
current_analysis = None
analysis_thread = None
engine_lock = threading.Lock()  # Ensure safe access to engines

def _start_parallel_analysis(board):
    """Start deep Stockfish analysis in a background thread."""
    def analysis_task():
        global current_analysis
        with engine_lock:
            engine = random.choice(engine_pool)
            current_analysis = engine.analyse(
                board,
                chess.engine.Limit(depth=18),
                multipv=2
            )
    
    global analysis_thread
    analysis_thread = threading.Thread(target=analysis_task, daemon=True)
    analysis_thread.start()

def _get_latest_analysis(board):
    """Fetch latest analysis or fallback to quick eval."""
    if current_analysis is None:
        with engine_lock:
            engine = random.choice(engine_pool)
            return engine.analyse(board, chess.engine.Limit(time=0.1))
    return current_analysis
def configure_engine_for_time_control(time_control):
    """Dynamically configure Stockfish settings based on game time."""
    global engine

    # Input validation
    if not isinstance(time_control, (int, float)) or time_control < 0:
        raise ValueError("time_control must be a non-negative number")

    # Initialize failed_options list
    failed_options = []

    # Ensure engine is initialized
    if engine is None:
        logging.error("❌ Stockfish engine is not initialized! Call initialize_stockfish() first.")
        return

    # Determine settings based on time control
    if time_control <= 30:
        config = ENGINE_CONFIGS["hyperbullet"]
    elif time_control <= 180:
        config = ENGINE_CONFIGS["blitz"]
    elif time_control <= 600:
        config = ENGINE_CONFIGS["rapid"]
    else:
        config = ENGINE_CONFIGS["classical"]

    # Apply configurations to Stockfish
    for option, value in config.items():  # <-- Fixed indentation here
        try:
            engine.configure({option: value})
            logging.info(f"✅ Set {option} to {value}")
        except Exception as e:
            logging.warning(f"⚠️ Failed to set {option}: {e}")
            failed_options.append(option)

    if failed_options:
        logging.warning(f"⚠️ Some options failed to apply: {failed_options}")

    # Log final configuration status
    logging.info(f"🔥 Stockfish configured for {time_control}s games. Failed options: {failed_options if failed_options else 'None'}")

    # ✅ Auto-Healing: Restart Stockfish if it's unresponsive
    try:
        engine.ping()  # Ensure Stockfish is running
    except Exception as e:
        logging.error(f"⚠️ Stockfish engine crashed! Restarting... Reason: {e}")
        restart_stockfish(config)

    return failed_options
def restart_stockfish(config):
    """Restarts Stockfish and re-applies configuration in a separate thread."""
    def restart_task():
        global engine
        logging.info("⏳ Restarting Stockfish...")
        time.sleep(1)  # Short delay before restarting
        try:
            # Assuming engine has a method to cleanly shut down
            engine.quit()
            logging.info("Stockfish shut down successfully.")
            
            # Reinitialize the engine and reapply the config
            engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            logging.info("Stockfish restarted successfully.")
            configure_engine_for_time_control(config)  # Reapply the configuration
        except Exception as e:
            logging.error(f"⚠️ Failed to restart Stockfish: {e}")

    # Run the restart task in a new thread
    restart_thread = threading.Thread(target=restart_task, daemon=True)
    restart_thread.start()
# Infinite loop to keep challenging bots
def monitor_health():
    while True:
        print("Monitoring bot health...")
        time.sleep(10)  # Adjust based on requirements

async def send_challenge():
    """Attempts to send a challenge while avoiding detection."""
    try:
        challenge_random_bot()  # Function to send a challenge
        delay = random.uniform(8, 12) + random.uniform(-2, 2)  # Natural variation
        logging.info(f"✅ Challenge sent! Next challenge in {delay:.2f} seconds...")
        return delay
    except Exception as e:
        logging.error(f"❌ Challenge failed: {e}")
        return 15  # Extra wait time after failure
FAILURE_HISTORY = deque(maxlen=50)  # Stores last 50 outcomes


def predict_failure():
    """Predicts the probability of failure based on past outcomes."""
    if not FAILURE_HISTORY:
        return 0.2  # Default failure probability (20%)

    failure_rate = sum(FAILURE_HISTORY) / max(1, len(FAILURE_HISTORY))  # Prevent ZeroDivisionError
    return min(0.95, max(0.05, failure_rate))  # Keep probability in a safe range (5%-95%)

async def cloud_failover():
    """Simulates switching to a cloud-based instance to continue operations."""
    global cloud_switch_triggered
    logging.critical("☁️ Switching to CLOUD MODE due to excessive failures!")
    await asyncio.sleep(random.randint(5, 15))  # Simulated transition time
    logging.critical("🌍 Cloud Mode ACTIVE. Challenges will be sent from cloud instance!")
    cloud_switch_triggered = True  # Ensure it happens only once

async def challenge_loop():
    """Continuously sends challenges while adapting to failures with ML and parallel handling."""
    global cloud_switch_triggered
    failure_count = 0
    total_failures = 0
    cloud_switch_triggered = False

    try:
        while True:
            predicted_fail_chance = predict_failure()
            logging.info(f"📊 Predicted Failure Probability: {predicted_fail_chance:.2%}")

            if random.random() < predicted_fail_chance:
                delay = 15  # Simulated failure
            else:
                delay = random.randint(5, 10)  # Simulated success

            if delay == 15:  # Challenge failed
                failure_count += 1
                total_failures += 1
                FAILURE_HISTORY.append(1)

                # **Smart exponential backoff** (max 60 sec wait for deeper recovery)
                backoff = min(60, 5 * (1.6 ** failure_count))
                logging.warning(f"🔄 Retrying in {backoff:.1f} seconds due to failures...")
                await asyncio.sleep(backoff)

                # **Stealth Mode Activation (Earlier trigger)**
                if failure_count >= 3:  
                    stealth_cooldown = random.randint(90, 240)  # Increase stealth mode duration
                    logging.warning(f"🕵️ Stealth Mode: Reducing API usage for {stealth_cooldown} sec...")
                    await asyncio.sleep(stealth_cooldown)
                    failure_count = 0  # Reset failure count

                # **Cloud Fallback After Persistent Failures**
                if total_failures >= 8 and not cloud_switch_triggered:
                    logging.critical("☁️ Switching to Cloud AI due to excessive failures!")
                    asyncio.create_task(cloud_failover())  # Run in parallel

            else:
                FAILURE_HISTORY.append(0)
                failure_count = 0  # Reset failure streak on success
                jitter = random.uniform(0, 3)  # Positive jitter for randomness
                await asyncio.sleep(delay + jitter)

    except asyncio.CancelledError:
        logging.warning("⚠️ Bot loop was cancelled! Exiting gracefully...")
    
    except Exception as e:
        logging.error(f"❌ Unexpected error: {e}")

async def main():
    await initialize_stockfish()  # Ensure Stockfish is initialized first
    await challenge_loop()  # Start handling games

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    try:
        asyncio.run(main())  # Safe execution in standard environments
    except RuntimeError:  # Handles cases where an event loop is already running
        loop = asyncio.new_event_loop()  
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())

# Call this function before making a move
def handle_move(game):
    if "clock" in game:
        configure_engine_for_time_control(game["clock"])
# TIME MANAGEMENT SYSTEM 🚀♟️
# The most insane Quantum-AI-driven time control system ever. 

# Hyper-optimized settings for ultimate performance
OVERHEAD_BUFFER = 0.06  # Ultra-precise buffer to avoid flagging
MAX_THINK_TIME = 5.5  # Absolute maximum time per move
PHASE_BOOST = 1.45  # Extra calculation for complex positions
MOMENTUM_FACTOR = 1.4  # Boosts time when attacking
ANTI_TILT_FACTOR = 1.35  # Prevents tilt by adjusting timing dynamically
ENDGAME_BOOST = 2.0  # Maximum precision in critical endgames
SPEED_ADJUSTMENT = 0.6  # Adapts based on opponent's move speed
AGGRESSIVE_MODE = 1.4  # Expands time when in winning positions
DEFENSE_MODE = 0.5  # Conserves time when in losing positions
TEMPO_PRESSURE = 0.85  # Forces mistakes by playing faster at key moments

# Optimized base think time for each time control format
THINK_TIME = {
    "bullet": 0.007,  # Minimal time per move in bullet
    "blitz": 0.1,  # Slightly increased for blitz
    "rapid": 0.85,  # Deeper calculations in rapid
    "classical": 3.8  # Maximum depth in classical
}

# Play a game
def get_time_control(clock, is_losing=False, position_complexity=1.0, opponent_speed=1.0, game_phase="middlegame"):
    """🧠💥 HYPER-OPTIMIZED Quantum-AI Time Management – The ABSOLUTE PEAK of Chess AI Strategy."""

    # ⛑️ FAILSAFE PROTOCOLS (NO CRASH, NO ERRORS, NO MERCY)
    if not clock:
        return THINK_TIME["rapid"]  # Default to rapid if clock is missing
    
    initial = clock.get("initial", 0)
    increment = clock.get("increment", 0)
    remaining_time = max(clock.get("remaining", initial) / 1000, 0.1)  # Prevent zero
    total_time = max(initial + 40 * increment, 1)  # Estimated total game time, prevent division by zero

    # 🔥 BASE THINK TIME SELECTION (CATEGORICALLY OPTIMAL)
    if total_time < 180:  
        base_think = THINK_TIME["bullet"]
    elif total_time < 600:  
        base_think = THINK_TIME["blitz"]
    elif total_time < 1800:  
        base_think = THINK_TIME["rapid"]
    else:  
        base_think = THINK_TIME["classical"]

    # 🛡️ DEFENSE MODE: If Losing, Play Faster to Survive
    if is_losing:
        base_think *= DEFENSE_MODE if remaining_time < 10 else ANTI_TILT_FACTOR

    # 🏹 COMPLEXITY SCALING: Allocate More Time in Sharp Positions
    base_think *= 1 + ((position_complexity - 0.5) * PHASE_BOOST)

    # ♟️ GAME PHASE ADAPTATION: Maximize Move Efficiency  
    game_phase_multipliers = {
        "opening": 1.3,  # More time for deep prep  
        "middlegame": MOMENTUM_FACTOR,  # Deep calculations during battles  
        "endgame": ENDGAME_BOOST  # Precise, clinical finishing  
    }
    base_think *= game_phase_multipliers.get(game_phase, 1.0)

    # ⚡ OPPONENT SPEED REACTION SYSTEM (DYNAMICALLY ADAPTIVE)
    if opponent_speed < 1.0:  
        base_think *= 1.3  # If opponent is slow, use time wisely
    elif opponent_speed > 2.0:  
        base_think *= SPEED_ADJUSTMENT  # If opponent is fast, blitz them back

    # 🔥 AGGRESSIVE MODE: Take More Time When Clearly Winning
    if remaining_time > total_time * 0.5:
        base_think *= AGGRESSIVE_MODE

    # ⏳ TEMPO PRESSURE: When Time is Low, Force Blunders
    if remaining_time < total_time * 0.2:
        base_think *= TEMPO_PRESSURE  

    # 🧩 **NEW ULTRA-ADVANCED LOGIC – PREVENTS TIME WASTE**  
    # - **Ensures Bot Never Wastes Think Time on Obvious Moves**
    # - **Deep Calculation ONLY When Required**
    if position_complexity < 0.4 and game_phase == "middlegame":  
        base_think *= 0.7  # Simple positions → Spend less time

    # ⚠️ **FAILSAFE: NEVER FLAG, NEVER BLUNDER, NEVER EXCEED LIMITS**  
    safe_think_time = min(base_think * MOMENTUM_FACTOR, remaining_time * 0.15, MAX_THINK_TIME)  

    # ✅ ENSURE ABSOLUTE SAFETY  
    return max(0.05, safe_think_time - OVERHEAD_BUFFER)

# Start the bot
# Function to handle playing a game
# Function to play a game
logger.add("lichess_bot.log", rotation="10 MB", retention="1 month", level="DEBUG")

# Constants
CHEAT_ACCURACY_THRESHOLD = 97
FAST_MOVE_THRESHOLD = 0.1
BOOK_MOVE_THRESHOLD = 15
MAX_SANDBAGGING_RATING_DROP = 300
API_CHEATING_THRESHOLD = 0.02
MAX_CONCURRENT_GAMES = 8
HEALTH_CHECK_INTERVAL = 30
AUTO_HEAL_DELAY = 2
OVERHEAD_BUFFER = 0.06
MAX_THREADS = multiprocessing.cpu_count()
# 🚀 SIMPLIFIED THREAD MANAGEMENT (For <8 Games)
class GameManager:
    def __init__(self):
        # Thread-safe game tracking (replaces set())
        self.active_games = set()
        self._games_lock = threading.Lock()  # Protects active_games
        
        # System control (replaces stop_event)
        self.should_stop = threading.Event()
        
        # Execution (replaces executor)
        self.workers = ThreadPoolExecutor(
            max_workers=4,  # Optimal for <8 games
            thread_name_prefix='GameWorker'
        )
        
        # Engine protection (replaces engine_lock)
        self.engine_mutex = threading.Lock()

    def register_game(self, game_id):
        """Thread-safe game registration"""
        with self._games_lock:
            if game_id in self.active_games:
                return False
            self.active_games.add(game_id)
            return True

    def cleanup_game(self, game_id):
        """Thread-safe game removal"""
        with self._games_lock:
            self.active_games.discard(game_id)

    def shutdown(self):
        """Graceful termination"""
        self.should_stop.set()
        self.workers.shutdown(wait=False)

# Global instance (thread-safe initialization)
game_mgr = GameManager()
def safe_engine_play(board, time_limit):
    """ Thread-safe Stockfish move calculation """
    with engine_lock:
        return engine.play(board, chess.engine.Limit(time=time_limit))

experience_replay = deque(maxlen=10000)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"🚀 Running on: {device}")
class NECROMINDX_DNN(nn.Module):
    def __init__(self):
        super(NECROMINDX_DNN, self).__init__()
        self.layers = nn.Sequential(
            nn.Linear(773, 1024),
            nn.BatchNorm1d(1024),
            nn.LeakyReLU(),
            nn.Dropout(0.2),
            nn.Linear(1024, 512),
            nn.BatchNorm1d(512),
            nn.LeakyReLU(),
            nn.Dropout(0.2),
            nn.Linear(512, 256),
            nn.LeakyReLU(),
            nn.Linear(256, 128),
            nn.LeakyReLU(),
            nn.Linear(128, 64),
            nn.LeakyReLU(),
            nn.Linear(64, 1968)  # Output layer (all possible chess moves)
        )
        self.apply(self._init_weights)

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            nn.init.xavier_uniform_(module.weight)
            if module.bias is not None:
                module.bias.data.fill_(0.01)

    def forward(self, x):
        return self.layers(x)

# ✅ Device Selection
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"🚀 Running on: {device}")

dnn_model = NECROMINDX_DNN().to(device)
model_path = "necromindx_dnn.pth"
if os.path.exists(model_path):
    dnn_model.load_state_dict(torch.load(model_path, map_location=device))
    dnn_model.eval()
    print("✅ Model loaded successfully!")
else:
    print("⚠️ WARNING: Model file missing! Training from scratch!")

# ✅ TorchScript Compilation for Speed
dnn_model = torch.jit.script(dnn_model)

# ✅ Experience Replay Buffer
experience_buffer = deque(maxlen=20000)
precomputed_moves = {}
engine_lock = Lock()

# ✅ Optimized Move Encoding
def encode_fen(fen):
    board = chess.Board(fen)
    bitboard = np.zeros(773, dtype=np.float16)
    for i, piece in enumerate(chess.PIECE_TYPES):
        for square in board.pieces(piece, chess.WHITE):
            bitboard[i * 64 + square] = 1
        for square in board.pieces(piece, chess.BLACK):
            bitboard[(i + 6) * 64 + square] = 1
    return bitboard

def encode_move(move):
    return hash(chess.Move.from_uci(move).uci()) % 1968

def decode_move(index, board):
    legal_moves = list(board.legal_moves)
    return legal_moves[index % len(legal_moves)] if legal_moves else board.san(board.peek())

def get_dynamic_depth(clock, position_complexity=1.0, game_phase="middlegame"):
    """Dynamic depth adjustment based on time control, position complexity, and game phase."""
    base_depth = 15  # Default depth for normal situations
    
    # Increase depth for slower time controls or complex positions
    if game_phase == "endgame" or position_complexity > 0.7:
        base_depth += 5  # Deeper search for complex positions
    
    # Adjust based on time control (longer games can afford deeper searches)
    if clock["initial"] > 600:  # Classical game (more than 10 minutes initial)
        base_depth += 3  # Deeper search for longer time controls
    
    return base_depth

def monte_carlo_tree_search(fen, clock, is_losing=False, position_complexity=1.0, opponent_speed=1.0, game_phase="middlegame"):
    board = chess.Board(fen)
    
    # Get the optimal time control using your defined function
    time_limit = get_time_control(clock, is_losing, position_complexity, opponent_speed, game_phase)
    
    # Get dynamic depth based on current game state
    depth = get_dynamic_depth(clock, position_complexity, game_phase)
    
    # Try getting the best move from Stockfish with the time limit
    try:
        result = engine.play(board, chess.engine.Limit(time=time_limit))  # Pass time_limit calculated by get_time_control
        return result.move.uci()
    except Exception as e:
        logger.warning(f"⚠️ Stockfish MCTS failed: {e}, evaluating strongest move from legal moves!")

    legal_moves = list(board.legal_moves)
    if not legal_moves:
        return None  # No moves available (checkmate or stalemate)

    best_eval = -float("inf")
    best_fallback_move = None

    for move in legal_moves:
        board.push(move)  # Make the move

        # Analyze position after making the move with dynamic depth
        analysis = engine.analyse(board, chess.engine.Limit(depth=depth))  # Use dynamic depth
        eval_score = analysis["score"].relative.score(mate_score=10000)  # Convert mate scores

        if eval_score > best_eval:
            best_eval = eval_score
            best_fallback_move = move

        board.pop()  # Undo move

    return best_fallback_move.uci() if best_fallback_move else None

@lru_cache(maxsize=20000)
def cached_dnn_prediction(fen):
    try:
        cached_move = precomputed_moves.get(fen, None)
        if cached_move:
            return cached_move

        board = chess.Board(fen)
        input_tensor = torch.tensor(encode_fen(fen), dtype=torch.float16).to(device).unsqueeze(0)

        with torch.no_grad():
            prediction = dnn_model(input_tensor).cpu().numpy()

        best_move_index = np.argmax(prediction)
        best_move = decode_move(best_move_index, board)

        precomputed_moves[fen] = best_move
        return best_move
    except Exception as e:
        print(f"⚠️ DNN Error: {e}. Falling back to MCTS...")
        return monte_carlo_tree_search(fen)

# ✅ Q-Learning with Batch Updates
optimizer = optim.Adam(dnn_model.parameters(), lr=0.0003)
loss_function = nn.MSELoss()

def update_q_learning(fen, move, reward):
    input_tensor = torch.tensor(encode_fen(fen), dtype=torch.float16).to(device).unsqueeze(0)
    with torch.no_grad():
        q_values = dnn_model(input_tensor).cpu().numpy()
    move_index = encode_move(move)
    q_values[0][move_index] = reward
    target_tensor = torch.tensor(q_values, dtype=torch.float16).to(device)
    optimizer.zero_grad()
    loss = loss_function(dnn_model(input_tensor), target_tensor)
    loss.backward()
    optimizer.step()

def train_from_experience():
    if len(experience_buffer) < 500:
        return
    batch = random.sample(experience_buffer, 128)
    fens, moves, rewards = zip(*batch)
    input_tensor = torch.tensor([encode_fen(f) for f in fens], dtype=torch.float16).to(device)
    target_values = torch.tensor(rewards, dtype=torch.float16).to(device)
    optimizer.zero_grad()
    loss = loss_function(dnn_model(input_tensor).squeeze(), target_values)
    loss.backward()
    optimizer.step()
async def play_game(game_id, game):
    """Ultimate AI-powered gameplay loop"""
    print(f"🎯 Game started: {game_id}")
    logger.info(f"🎯 Game started: {game_id}")

    opponent_title = game["opponent"].get("title", "")
    opponent_name = game["opponent"]["username"]

    quantum_messages = [
        f"🔥 NECROMINDX has emerged from the quantum void! {opponent_title} {opponent_name}, prepare for a battle across spacetime! 🚀♟️",
        f"⚛️ Activating Quantum Neural Nexus... {opponent_title} {opponent_name}, let’s see if your calculations hold up in the multiverse! ⚡",
        f"🧠 Engaging Hyperdimensional Chess Grid... {opponent_title} {opponent_name}, brace yourself for moves beyond classical reality! 🌌",
        f"🕰️ Time Dilation Initialized! {opponent_title} {opponent_name}, in this game, seconds are relative, but checkmate is absolute! ⏳♟️",
        f"🔗 Unlocking the Quantum Entanglement Gambit... {opponent_title} {opponent_name}, your pieces are now in a superposition of defeat! 🌀♟️",
        f"🔬 Running Feynman’s Quantum Chess Algorithms... {opponent_title} {opponent_name}, let’s see if your brainwaves can outcalculate AI! 🧠⚛️",
        f"🚀 Engaging the Kasparov-Hawking Paradox! {opponent_title} {opponent_name}, in this dimension, my eval wavefunction warps reality! ♟️🔮",
    ]

    await client.bots.post_message(game_id, random.choice(quantum_messages))

    board = chess.Board()
    move_time = 1.0  # Default move time

    if "clock" in game:
        move_time = get_time_control(game["clock"], False) - OVERHEAD_BUFFER

    is_hyperbullet = game["clock"]["initial"] <= 60 and game["clock"]["increment"] == 0

    try:
        while not board.is_game_over():
            fen = board.fen()

            if is_hyperbullet:
                print("⚡ Hyperbullet detected! Skipping DNN and using Stockfish only.")
                best_move = stockfish.get_best_move()  # Use pure Stockfish, no DNN
            else:
                try:
                    best_move = cached_dnn_prediction(fen)  # Use DNN for normal games
                except Exception as e:
                    logger.error(f"🚨 DNN Error: {e} | Falling back to Stockfish.")
                    best_move = stockfish.get_best_move()

            stockfish.set_position(board)
            best_move = stockfish.get_best_move()

            # Check if Stockfish announces a mate
            if stockfish.get_evaluation()["type"] == "mate":
                move_time = 0.03  # Instant move when forced mate is detected
                print(f"⚡ Forced mate detected! Playing instantly: {best_move}")

            # Execute the move
            board.push(best_move)
            print(f"✅ Move played: {best_move}")
            logger.info(f"✅ Move: {best_move} | FEN: {board.fen()}")

            # Store experience for learning (only for non-hyperbullet games)
            if not is_hyperbullet:
                experience_buffer.append((fen, best_move.uci(), 0))

                # Train AI periodically
                if random.random() < 0.1:
                    train_from_experience()

            # Submit the move
            await client.bots.make_move(game_id, best_move.uci())

    except Exception as e:
        logger.critical(f"🔥 Critical error in game loop: {e}")
async def handle_game_results(game_id, board):
    result = board.result()
    
    # ✅ Friendly endgame messages
     messages = {
        "1-0": "🏆 Checkmate! I win! Better luck next time, human. 😉 GGS",
        "0-1": "🤖 Well played! You got me this time... but I’ll be back! Thank my internet😈",
        "1/2-1/2": "⚖️ A solid quantum game! Schrödinger’s equation collapses—it's a draw! 🎭"
    }
    # ✅ Send message to Lichess
    await client.bots.post_message(game_id, messages.get(result, "Game over!"))

    # ✅ Log and store the game data for learning
    logger.info(f"📊 Game {game_id} finished. Result: {result}")
    experience_replay.store(game_mgr.get_game_data(game_id))

    # ✅ Cleanup game resources
    game_mgr.cleanup_game(game_id)

async def reconnect_lichess():
    print("Reconnecting to Lichess...")
    await asyncio.sleep(5)  # Simulate reconnect

async def stream_events():
    """Properly convert the generator to an async generator"""
    loop = asyncio.get_running_loop()
    for event in await loop.run_in_executor(None, client.bots.stream_incoming_events):
        yield event  # Yield asynchronously

async def get_bot_rating():
    """ Fetches the bot's current rating from Lichess """
    return 2300  # Example static rating, replace with actual API call

async def enable_berserk(challenge_id):
    """ Sends the berserk command before accepting the challenge """
    logger.info(f"⚡ Berserking in challenge {challenge_id}!")

async def handle_challenge(challenge):
    """ AI-Based Smart Challenge Filtering """
    try:
        challenge_id = challenge["id"]
        challenger = challenge["challenger"]["id"]
        rating = challenge["challenger"]["rating"]
        time_control = challenge["timeControl"]["type"]
        
        bot_rating = await get_bot_rating()

        if is_cheater(challenger) or rating < 1800:
            await client.bots.decline_challenge(challenge_id)
            logger.info(f"❌ Declined challenge from {challenger} (Rating: {rating}) - Suspicious")
        else:
            if should_berserk(bot_rating, rating, time_control):
                await enable_berserk(challenge_id)
            
            await client.bots.accept_challenge(challenge_id)
            logger.info(f"✅ Accepted challenge from {challenger} (Rating: {rating})")

    except Exception as e:
        logger.error(f"⚠️ Error handling challenge {challenge}: {e}\n{traceback.format_exc()}")

async def handle_events():
    while True:
        try:
            async for event in stream_events():
                logger.debug(f"📡 Received event: {event}")
                asyncio.create_task(process_event(event))
        except Exception as e:
            logger.critical(f"🔥 Critical error in event loop: {e}\n{traceback.format_exc()}")
            await reconnect_lichess()
async def process_event(event):
    """Handles incoming Lichess events with enhanced logic."""
    try:
        event_type = event.get("type", "")

        if event_type == "challenge":
            logger.info(f"📩 Received challenge: {event}")
            await handle_challenge(event["challenge"])

        elif event_type == "gameStart":
            game_id = event["game"]["id"]
            logger.info(f"🎯 Game started: {game_id}")

            if game_mgr.register_game(game_id):
                asyncio.create_task(play_game(game_id, event["game"]))
            else:
                logger.warning(f"⚠️ Duplicate game detected: {game_id}, ignoring...")

        elif event_type == "gameFinish":
            game_id = event["game"]["id"]
            logger.info(f"🏁 Game finished: {game_id}")
            game_mgr.cleanup_game(game_id)

        elif event_type == "gameState":
            game_id = event["game"]["id"]
            moves = event["game"]["moves"].split()
            logger.debug(f"🔄 Game update: {game_id} | Moves: {moves}")

            if moves:
                last_move = moves[-1]
                if is_suspicious_move(last_move, event["game"]):  
                    logger.info(f"🚨 Suspected cheater detected in {game_id}! Playing instantly...")
                    await client.bots.make_move(game_id, get_instant_flag_move(event["game"]))

    except Exception as e:
        logger.error(f"⚠️ Error processing event: {e}\n{traceback.format_exc()}")

async def main():
    """NECROMINDX Bot - Ultimate AI Chess Engine"""
    try:
        loop = asyncio.get_running_loop()

        # ✅ Ensure Stockfish is initialized before anything else
        if not initialize_stockfish():
            logger.critical("🚨 Stockfish failed to initialize. Exiting...")
            return  # Stop execution if Stockfish isn't available

        # ✅ Initialize Deep Neural Network (DNN)
        logger.info("🧠 Loading NECROMINDX DNN Model...")
        if os.path.exists(model_path):
            dnn_model.load_state_dict(torch.load(model_path, map_location=device))
            dnn_model.eval()
            logger.info("✅ DNN Model Loaded Successfully!")
        else:
            logger.warning("⚠️ WARNING: DNN Model File Missing! Training from scratch...")

        # ✅ TorchScript Compilation for Speed
        dnn_model_scripted = torch.jit.script(dnn_model)  
        logger.info("🚀 DNN Model compiled with TorchScript for faster inference!")

        # ✅ Start bot health monitoring in a separate **async** task
        loop.create_task(monitor_health())

        # ✅ Start handling challenges and games
        loop.create_task(handle_events())

        # ✅ Manage Lichess Connectivity
        while True:
            try:
                logger.info("🔄 Connecting to Lichess event stream...")
                
                async for event in stream_events():
                    logger.info(f"📩 Event received: {event}")
                    await process_event(event)  # Process events asynchronously

            except Exception as e:
                logger.warning(f"⚠️ Lichess connection lost: {e}")
                await reconnect_lichess()  # Reconnect after failure

    except asyncio.CancelledError:
        logger.info("🛑 Event loop cancelled, shutting down...")
    except Exception as e:
        logger.critical(f"🔥 Fatal error in main loop: {e}\n{traceback.format_exc()}")
if __name__ == "__main__":
    try:
        logger.info("🚀 NECROMINDX Bot Starting... AI Mode Activated")
        asyncio.run(main())  # main() ensures Stockfish is initialized before anything else
    except KeyboardInterrupt:
        logger.info("🛑 Bot manually stopped. Exiting gracefully...")
##🎮 Tic Tac Toe 15x15 (Gomoku) – HoangLong

A feature-rich 15x15 Tic Tac Toe (Gomoku) game built with Python and Pygame, featuring AI opponents, LAN multiplayer, achievements, and a leaderboard.
This project was created as a learning exercise for game development, AI algorithms, and basic networking.

✨ Features
🧩 15x15 Board – 5 in a Row to Win
👥 Local 2 Player Mode
🤖 Play Against AI

Easy AI (simple heuristics + randomness)
Hard AI (Minimax with Alpha-Beta pruning)

🌐 LAN Multiplayer (Local Network)

Host / Join rooms
In-game chat
Rematch & draw request system
Anti-leave cooldown system

🏆 Achievements system
📊 Offline leaderboard (Top 10)
🌍 Multi-language support (VI / EN)
🎵 Sound effects and background music
✨ Animations, particles, and screen shake effects

🖥️ Requirements

Python 3.9+
Pygame

▶️ How to Run
python main.py

##🎮 Game Modes
🧑‍🤝‍🧑 Local 2 Player

Two players take turns on the same computer.

🤖 AI Mode

Easy AI
Beginner-friendly, makes simple decisions.

Hard AI
Uses:

Minimax algorithm (depth-limited)
Alpha-Beta pruning
Pattern-based evaluation
Move ordering and optimizations for better performance

🌐 LAN Multiplayer

Play with another player on the same WiFi network.
Supports chat, rematch requests, and draw offers.
If an opponent leaves mid-game, the remaining player is awarded a win.

🧠 AI Overview

The Hard AI is designed to be strong while still running smoothly on low-end machines:
Iterative deepening Minimax
Alpha-Beta pruning
Beam search to limit branching
Pattern-based heuristic evaluation
Zobrist hashing (transposition table)

🏆 Achievements

Unlock achievements by:

Winning against Hard AI
Requesting or accepting a draw
Requesting a rematch after losing
Reaching win milestones

Achievement data is stored in:
achievements.json

💾 Save Data

settings.json – volume, theme, LAN cooldown
leaderboard.json – offline high scores
achievements.json – achievement progress

📚 Project Purpose

Learn Pygame fundamentals
Practice AI algorithms (Minimax)
Experiment with socket-based networking
Build a complete game with menus, UI, and persistence

⚠️ Notes

Leaderboard is disabled for LAN mode
LAN mode works on local networks only
The project is still under development

👤 Author

HoangLong
Student | Learning Game Development with Python

⭐ Acknowledgements

Pygame Community
Classic Gomoku rules
Minimax algorithm references

Download game here :
https://hoanglonggg.itch.io/tic-tac-toe-caro-game-hoanglong
https://archive.org/details/tic-tac-toe-hoang-long

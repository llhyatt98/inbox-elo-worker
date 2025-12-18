# inbox-elo-worker
Eval worker using Stockfish

# Project Context: Daily Chess Coach (Backend Worker)
I am building the background analysis engine for a chess improvement SaaS.
This is a headless Python script that runs continuously (or via Cron) to process user games.

## Tech Stack
- **Runtime:** Python 3.11+
- **Libraries:** `python-chess` (PGN parsing), `psycopg2` (PostgreSQL connection), `requests` (API calls).
- **Engine:** Stockfish 16 (Binary executable).
- **Deployment:** Docker container running on Railway/Render.

## Architectural Role
This script acts as the **"Model" and "Processor"**.
- It is decoupled from the frontend.
- It communicates solely through the Supabase `analysis_jobs` table.
- It handles all CPU-intensive tasks.

## The Logic Flow (The Loop)
The worker performs the following "Job" loop:
1. **Poll:** Selects a row from Supabase `analysis_jobs` where `status` is 'PENDING'.
2. **Fetch:** Uses the Chess.com Public API to find the user's *most recent* game.
   - Logic: Get Archives -> Get Current Month URL -> Sort by Date -> Get Last PGN.
3. **Analyze:**
   - Spawns a local Stockfish process via `python-chess`.
   - Iterates through the game moves.
   - Identifies the "Key Moment": A specific move where the evaluation swung by >150 centipawns (a blunder).
4. **Save:** Updates the Supabase row with `status` = 'COMPLETED' and saves the `fen` (board state), `blunder_move`, and `best_move` to a JSON column.
5. **Notify:** (Optional step) Triggers the transactional email via Postmark/Resend.

## Environment Constraints
- **Stockfish Path:** Must handle environment variables (`STOCKFISH_PATH`) to distinguish between local development (macOS binary) and production (Linux binary in Docker).
- **Rate Limiting:** Must respect Chess.com's API headers to avoid bans.

## Development Setup

### Prerequisites
- Docker and Docker Compose installed
- `.env` file with `DATABASE_URL` configured

### Quick Start

1. **Create `.env` file:**
   ```bash
   cp env.example .env
   # Edit .env with your DATABASE_URL
   ```

2. **Build and run with Docker Compose:**
   ```bash
   # Production mode (auto-restarts)
   docker-compose up --build
   
   # Development mode (with live code reloading)
   docker-compose -f docker-compose.dev.yml up --build
   ```

3. **Run worker manually in container (for debugging):**
   ```bash
   # Start container in background
   docker-compose -f docker-compose.dev.yml up -d
   
   # Execute worker inside container
   docker-compose -f docker-compose.dev.yml exec worker python worker.py
   
   # Or get a shell for interactive debugging
   docker-compose -f docker-compose.dev.yml exec worker /bin/bash
   ```

4. **Test database connection:**
   ```bash
   docker-compose exec worker python db.py
   ```

### Development Workflow

**Option 1: Local Development (No Docker)**
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="your_connection_string"
export STOCKFISH_PATH="/opt/homebrew/bin/stockfish"

# Run worker
python worker.py
```

**Option 2: Docker Development (Recommended)**
- Code changes are automatically reflected (volume mounted)
- Uses Linux Stockfish binary (matches production)
- No need to install Python dependencies locally

```bash
# Terminal 1: Start dev container (runs in background)
make dev

# Terminal 2: Test database connection
make test-db

# Terminal 2: Run the worker
make dev-run

# Or get an interactive shell
make dev-shell
# Then inside container: python worker.py

# View logs
make dev-logs

# Stop when done
make dev-stop
```

### Useful Docker Commands

```bash
# View logs
docker-compose logs -f worker

# Rebuild after dependency changes
docker-compose build --no-cache

# Stop and remove containers
docker-compose down

# Run one-off commands
docker-compose exec worker python -c "from db import test_connection; test_connection()"
```
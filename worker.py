#!/usr/bin/env python3
"""
Daily Chess Coach - Analysis Worker
Background worker that processes chess game analysis jobs from Supabase.
"""

import os
import time
import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime

import chess
import chess.engine
import requests
from psycopg2.extras import RealDictCursor

from db import get_db_connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ChessAnalysisWorker:
    """Worker that processes chess game analysis jobs."""
    
    def __init__(self):
        """Initialize the worker with configuration from environment variables."""
        # Test database connection on startup
        try:
            conn = get_db_connection()
            conn.close()
            logger.info("Database connection verified")
        except Exception as e:
            raise ValueError(f"Failed to connect to database: {e}")
        
        # Stockfish configuration
        self.stockfish_path = os.getenv('STOCKFISH_PATH', '/usr/bin/stockfish')
        if not os.path.exists(self.stockfish_path):
            logger.warning(f"Stockfish not found at {self.stockfish_path}")
        
        # Worker configuration
        self.poll_interval = int(os.getenv('POLL_INTERVAL', '5'))
        self.max_retries = int(os.getenv('MAX_RETRIES', '3'))
        
        # Chess.com API configuration
        self.chess_com_base_url = 'https://api.chess.com/pub'
    
    def poll_for_jobs(self) -> Optional[Dict[str, Any]]:
        """
        Poll database for pending analysis jobs.
        
        Returns:
            A job dictionary if found, None otherwise.
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT * FROM analysis_jobs
                        WHERE status = 'PENDING'
                        ORDER BY created_at ASC
                        LIMIT 1
                    """)
                    row = cur.fetchone()
                    if row:
                        return dict(row)
                    return None
        except Exception as e:
            logger.error(f"Error polling for jobs: {e}")
            return None
    
    def fetch_latest_game(self, username: str) -> Optional[str]:
        """
        Fetch the most recent game PGN from Chess.com for a given username.
        
        Args:
            username: Chess.com username
            
        Returns:
            PGN string if found, None otherwise.
        """
        try:
            # Get archives
            archives_url = f"{self.chess_com_base_url}/player/{username}/games/archives"
            archives_response = requests.get(archives_url, timeout=10)
            archives_response.raise_for_status()
            archives = archives_response.json()
            
            if not archives.get('archives'):
                logger.warning(f"No archives found for user {username}")
                return None
            
            # Get current month URL (most recent)
            current_month_url = archives['archives'][-1]
            
            # Get games for current month
            games_response = requests.get(current_month_url, timeout=10)
            games_response.raise_for_status()
            games_data = games_response.json()
            
            if not games_data.get('games'):
                logger.warning(f"No games found for user {username} in current month")
                return None
            
            # Sort by end_time and get the last game
            games = games_data['games']
            sorted_games = sorted(
                games,
                key=lambda x: x.get('end_time', 0),
                reverse=True
            )
            
            latest_game = sorted_games[0]
            return latest_game.get('pgn')
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching game from Chess.com: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching game: {e}")
            return None
    
    def analyze_game(self, pgn: str) -> Optional[Dict[str, Any]]:
        """
        Analyze a game to find the key blunder moment.
        
        Args:
            pgn: Game PGN string
            
        Returns:
            Dictionary with fen, blunder_move, and best_move, or None if no blunder found.
        """
        try:
            board = chess.Board()
            game = chess.pgn.read_game(chess.pgn.StringIO(pgn))
            
            if not game:
                logger.error("Failed to parse PGN")
                return None
            
            blunder_threshold = 1.5  # 150 centipawns = 1.5 pawns
            
            with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
                for node in game.mainline():
                    move = node.move
                    mover_color = board.turn  # Color of player making the move
                    
                    # Evaluate position before the move (from mover's perspective)
                    info_before = engine.analyse(board, chess.engine.Limit(depth=15))
                    score_before = info_before['score']
                    if mover_color == chess.WHITE:
                        eval_before = score_before.white().score(mate_score=10000) / 100.0
                    else:
                        eval_before = -score_before.white().score(mate_score=10000) / 100.0
                    
                    # Make the move
                    board.push(move)
                    
                    # Evaluate position after the move (from mover's perspective, now opponent's turn)
                    info_after = engine.analyse(board, chess.engine.Limit(depth=15))
                    score_after = info_after['score']
                    if mover_color == chess.WHITE:
                        eval_after = -score_after.white().score(mate_score=10000) / 100.0
                    else:
                        eval_after = score_after.white().score(mate_score=10000) / 100.0
                    
                    # Check for blunder (evaluation dropped significantly)
                    eval_swing = eval_before - eval_after  # Positive = position got worse
                    if eval_swing > blunder_threshold:
                        # Found the blunder
                        board.pop()  # Go back to position before the blunder
                        fen = board.fen()
                        
                        # Find best move from this position
                        best_info = engine.analyse(board, chess.engine.Limit(depth=20))
                        best_move = best_info.get('pv', [None])[0]
                        
                        return {
                            'fen': fen,
                            'blunder_move': move.uci(),
                            'best_move': best_move.uci() if best_move else None
                        }
            
            # No blunder found
            return None
            
        except FileNotFoundError:
            logger.error(f"Stockfish not found at {self.stockfish_path}")
            return None
        except Exception as e:
            logger.error(f"Error analyzing game: {e}")
            return None
    
    def update_job_status(
        self,
        job_id: int,
        status: str,
        analysis_result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """
        Update the job status in the database.
        
        Args:
            job_id: The job ID to update
            status: New status ('COMPLETED', 'FAILED', etc.)
            analysis_result: Optional analysis result data
            error: Optional error message
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Build update query
                    updates = ['status = %s', 'updated_at = %s']
                    values = [status, datetime.utcnow()]
                    
                    if analysis_result:
                        updates.append('analysis_data = %s')
                        values.append(json.dumps(analysis_result))
                    
                    if error:
                        updates.append('error_message = %s')
                        values.append(error)
                    
                    values.append(job_id)
                    
                    query = f"""
                        UPDATE analysis_jobs
                        SET {', '.join(updates)}
                        WHERE id = %s
                    """
                    
                    cur.execute(query, values)
                    conn.commit()
            
            logger.info(f"Updated job {job_id} to status {status}")
            
        except Exception as e:
            logger.error(f"Error updating job status: {e}")
    
    def process_job(self, job: Dict[str, Any]) -> bool:
        """
        Process a single analysis job.
        
        Args:
            job: Job dictionary from Supabase
            
        Returns:
            True if successful, False otherwise
        """
        job_id = job.get('id')
        username = job.get('username')
        
        if not username:
            logger.error(f"Job {job_id} missing username")
            self.update_job_status(job_id, 'FAILED', error='Missing username')
            return False
        
        logger.info(f"Processing job {job_id} for user {username}")
        
        # Fetch latest game
        pgn = self.fetch_latest_game(username)
        if not pgn:
            self.update_job_status(job_id, 'FAILED', error='Failed to fetch game')
            return False
        
        # Analyze game
        analysis_result = self.analyze_game(pgn)
        if not analysis_result:
            self.update_job_status(job_id, 'COMPLETED', error='No blunder found')
            return True
        
        # Save results
        self.update_job_status(job_id, 'COMPLETED', analysis_result=analysis_result)
        
        # TODO: Trigger email notification if configured
        # self.send_notification(job, analysis_result)
        
        return True
    
    def run(self):
        """Main worker loop."""
        logger.info("Starting Chess Analysis Worker")
        logger.info(f"Stockfish path: {self.stockfish_path}")
        logger.info(f"Poll interval: {self.poll_interval} seconds")
        
        while True:
            try:
                # Poll for jobs
                job = self.poll_for_jobs()
                
                if job:
                    self.process_job(job)
                else:
                    logger.debug("No pending jobs found")
                
                # Wait before next poll
                time.sleep(self.poll_interval)
                
            except KeyboardInterrupt:
                logger.info("Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in worker loop: {e}")
                time.sleep(self.poll_interval)


def main():
    """Entry point for the worker."""
    try:
        worker = ChessAnalysisWorker()
        worker.run()
    except Exception as e:
        logger.error(f"Failed to start worker: {e}")
        raise


if __name__ == '__main__':
    main()


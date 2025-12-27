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

import re
import requests
from psycopg2.extras import RealDictCursor

from db import get_db_connection
from email_service import EmailService
from analysis import AnalysisService

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
        except Exception as e:
            raise ValueError(f"Failed to connect to database: {e}")
        
        # Stockfish configuration
        self.stockfish_path = os.getenv('STOCKFISH_PATH', '/usr/bin/stockfish')
        
        # If configured path doesn't exist, try to find it in PATH or common locations
        if not os.path.exists(self.stockfish_path):
            import shutil
            logger.warning(f"Stockfish not found at {self.stockfish_path}, searching in PATH...")
            
            # Try shutil.which
            found_path = shutil.which('stockfish')
            
            # Check common locations if not found in PATH
            if not found_path:
                for common_path in ['/usr/games/stockfish', '/usr/local/bin/stockfish']:
                    if os.path.exists(common_path):
                        found_path = common_path
                        break
            
            if found_path:
                # logger.info(f"Found Stockfish at {found_path}")
                self.stockfish_path = found_path
            else:
                logger.warning("Stockfish not found in any common location")
        
        # Worker configuration
        self.poll_interval = int(os.getenv('POLL_INTERVAL', '5'))
        self.max_retries = int(os.getenv('MAX_RETRIES', '3'))
        self.dev_mode = os.getenv('DEV_MODE', 'false').lower() == 'true'
        self.dev_email = os.getenv('TO_EMAIL')
        
        # Chess.com API configuration
        self.chess_com_base_url = 'https://api.chess.com/pub'
        
        # Initialize email service
        self.email_service = EmailService()

        # Disables sending emails
        self.send_emails = True
        
        # Initialize analysis service
        self.analysis_service = AnalysisService(self.stockfish_path)
    
    def poll_for_jobs(self) -> Optional[Dict[str, Any]]:
        """
        Poll database for pending analysis jobs and claim one atomically.
        
        Returns:
            A job dictionary if found, None otherwise.
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Atomic FETCH and UPDATE
                    # This finds a candidate, updates its last_run_at immediately to "lock" it
                    # from other workers, and returns the job details.
                    cur.execute("""
                        UPDATE analysis_jobs
                        SET last_run_at = NOW()
                        WHERE id = (
                            SELECT aj.id
                            FROM analysis_jobs aj
                            WHERE aj.status = 'PENDING'
                            AND (
                                aj.last_run_at IS NULL 
                                OR aj.last_run_at <= NOW() - aj.run_interval
                            )
                            ORDER BY aj.created_at ASC
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        RETURNING *, 
                        (SELECT chess_username FROM users WHERE id = analysis_jobs.user_id) as username,
                        (SELECT email FROM users WHERE id = analysis_jobs.user_id) as email
                    """)
                    row = cur.fetchone()
                    conn.commit() # Important: Commit the "lock" immediately
                    
                    if row:
                        return dict(row)
                    return None
        except Exception as e:
            logger.error(f"Error polling for jobs: {e}")
            return None

    def poll_dev_job(self) -> Optional[Dict[str, Any]]:
        """
        Poll for the latest pending analysis job for the dev email user.
        
        Returns:
            A job dictionary if found, None otherwise.
        """
        if not self.dev_email:
            logger.warning("TO_EMAIL not set, cannot poll for dev job")
            return None

        try:
            with get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Join with users table to get chess_username and filter by email
                    # Dev job only finds by email
                    cur.execute("""
                        SELECT aj.*, u.chess_username as username
                        FROM analysis_jobs aj
                        JOIN users u ON aj.user_id = u.id
                        WHERE aj.status = 'PENDING'
                        AND u.email = %s
                        ORDER BY aj.created_at DESC
                        LIMIT 1
                    """, (self.dev_email,))
                    row = cur.fetchone()
                    if row:
                        return dict(row)
                    return None
        except Exception as e:
            logger.error(f"Error polling for dev job: {e}")
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
            headers = {
                'User-Agent': 'DailyChessCoach/1.0 (contact@example.com)'
            }
            
            # Get archives
            archives_url = f"{self.chess_com_base_url}/player/{username}/games/archives"
            archives_response = requests.get(archives_url, headers=headers, timeout=10)
            archives_response.raise_for_status()
            archives = archives_response.json()
            
            if not archives.get('archives'):
                logger.warning(f"No archives found for user {username}")
                return None
            
            # Get current month URL (most recent)
            current_month_url = archives['archives'][-1]
            
            # Get games for current month
            games_response = requests.get(current_month_url, headers=headers, timeout=10)
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
    
    def update_job_status(
        self,
        job_id: str,
        status: str,
        analysis_result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """
        Update the job status in the database.
        
        Args:
            job_id: The job ID to update (UUID)
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
                        # Schema has analysis_result column, not analysis_data
                        updates.append('analysis_result = %s')
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

    def update_last_run(self, job_id: str):
        """
        Update the last_run_at timestamp for a job.
        
        Args:
            job_id: The job ID to update
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE analysis_jobs
                        SET last_run_at = NOW()
                        WHERE id = %s
                    """, (job_id,))
                    conn.commit()
            logger.info(f"Updated last_run_at for job {job_id}")
        except Exception as e:
            logger.error(f"Error updating last_run_at for job {job_id}: {e}")
    
    def process_job(self, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process a single analysis job.
        
        Args:
            job: Job dictionary from Supabase
            
        Returns:
            Dictionary with job results if successful, None otherwise
        """
        job_id = job.get('id')
        username = job.get('username')
        email = job.get('email', 'Unknown')
        
        if not username:
            logger.error(f"Job {job_id} missing username")
            # self.update_job_status(job_id, 'FAILED', error='Missing username')
            return None
        
        logger.info("="*100)
        logger.info(f"Processing job {job_id}")
        logger.info(f"User: {username} | Email: {email}")
        
        # Fetch latest game
        pgn = self.fetch_latest_game(username)
        if not pgn:
            logger.error(f"Failed to fetch game for job {job_id}")
            # self.update_job_status(job_id, 'FAILED', error='Failed to fetch game')
            return None
            
        logger.info(f"Successfully fetched game for {username}")
        
        # Parse players for logging
        white = "Unknown"
        black = "Unknown"
        white_match = re.search(r'\[White "(.*?)"\]', pgn)
        black_match = re.search(r'\[Black "(.*?)"\]', pgn)
        if white_match: white = white_match.group(1)
        if black_match: black = black_match.group(1)
        
        logger.info(f"Game fetched: {white} vs {black}")
        
        # Analyze game
        analysis_result = self.analysis_service.analyze_game(pgn, username)
        if not analysis_result:
            logger.info(f"Analysis complete (no blunder found) for job {job_id}")
            # self.update_job_status(job_id, 'COMPLETED', error='No blunder found')
            return {
                'job_id': job_id,
                'username': username,
                'email': email,
                'pgn': pgn,
                'analysis_result': None,
                'status': 'NO_BLUNDER'
            }
        
        # Save results
        logger.info(f"Analysis complete (blunder found) for job {job_id}")
        
        # self.update_job_status(job_id, 'COMPLETED', analysis_result=analysis_result)
        
        return {
            'job_id': job_id,
            'username': username,
            'email': email,
            'pgn': pgn,
            'analysis_result': analysis_result,
            'status': 'BLUNDER_FOUND'
        }
    
    def run(self):
        """Main worker loop."""
        logger.info("Starting Chess Analysis Worker")
        
        if self.dev_mode:
            logger.info(f"Running in DEV MODE (filtering for {self.dev_email})")
            try:
                job = self.poll_dev_job()
                if job:
                    result = self.process_job(job)
                    if result:
                        if self.send_emails:
                            # Send email
                            email_result = self.email_service.send_analysis_results(result)
                            if email_result:
                                self.update_last_run(job['id'])
                        else:
                            logger.info("Email sending disabled by configuration - Updating last_run_at anyway")
                            self.update_last_run(job['id'])
                else:
                    logger.info(f"No pending jobs found for {self.dev_email}")
            except Exception as e:
                logger.error(f"Error in dev mode: {e}")
            return
        
        while True:
            try:
                # Poll for jobs
                job = self.poll_for_jobs()
                
                if job:
                    result = self.process_job(job)
                    if result:
                        if self.send_emails:
                            # Send email
                            email_result = self.email_service.send_analysis_results(result)
                            if email_result:
                                self.update_last_run(job['id'])
                        else:
                            logger.info("Email sending disabled by configuration - Updating last_run_at anyway")
                            self.update_last_run(job['id'])
                else:
                    logger.info("No pending jobs found")
                
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


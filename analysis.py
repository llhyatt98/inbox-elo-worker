import logging
import io
import chess
import chess.engine
import chess.pgn
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class AnalysisService:
    """Service for analyzing chess games using Stockfish."""

    def __init__(self, stockfish_path: str):
        """
        Initialize the analysis service.
        
        Args:
            stockfish_path: Path to the Stockfish executable
        """
        self.stockfish_path = stockfish_path

    def analyze_game(self, pgn: str, username: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Analyze a game to find the key blunder moment.
        
        Args:
            pgn: Game PGN string
            username: Optional username to identify the player to analyze (White/Black)
            
        Returns:
            Dictionary with fen, blunder_move, and best_move, or None if no blunder found.
        """
        try:
            # Initialize game from PGN
            game = chess.pgn.read_game(io.StringIO(pgn))
            if not game:
                logger.error("Failed to parse PGN")
                return None
            
            # Initialize board with correct starting position (respects FEN)
            board = game.board()
            
            logger.info("--- Starting Game Analysis ---")
            
            # Determine user color
            user_color = None
            if username:
                white_player = game.headers.get("White", "")
                black_player = game.headers.get("Black", "")
                
                # Simple case-insensitive match
                if username.lower() in white_player.lower():
                    user_color = chess.WHITE
                    logger.info(f"Analyzing for user {username} (White)")
                elif username.lower() in black_player.lower():
                    user_color = chess.BLACK
                    logger.info(f"Analyzing for user {username} (Black)")
                else:
                    logger.warning(f"User {username} not found in players: {white_player} vs {black_player}. Analyzing both sides.")
            
            # Configuration
            blunder_threshold_cp = 150  # 1.5 pawns
            dead_game_threshold_cp = 500  # 5.0 pawns
            depth = 18
            multipv = 2
            
            with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
                for node in game.mainline():
                    mover_color = board.turn
                    actual_move = node.move
                    
                    # Format move string
                    move_number = board.fullmove_number
                    move_str = f"{move_number}. {actual_move.uci()}" if mover_color == chess.WHITE else f"{move_number}... {actual_move.uci()}"
                    
                    # Skip analysis if we are restricting to user_color and it's not their turn
                    if user_color is not None and mover_color != user_color:
                        board.push(actual_move)
                        continue
                        
                    # Analyze current position
                    # multipv=2 to find best move and potential alternatives
                    info = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=multipv)
                    
                    if not info:
                        board.push(actual_move)
                        continue
                        
                    # Get best move (PV #1)
                    best_pv = info[0]
                    best_move = best_pv.get("pv", [None])[0]
                    # Score from mover's perspective
                    best_score = best_pv["score"].pov(mover_color).score(mate_score=10000)
                    
                    # Check if game is "dead" (advantage > 5.0)
                    # We check absolute value because either side winning by a lot makes it dead
                    if abs(best_score) > dead_game_threshold_cp:
                        board.push(actual_move)
                        continue
                        
                    # Get actual move score
                    actual_score = None
                    pushed = False
                    
                    # Check if actual move is in our multipv results
                    for pv_info in info:
                        pv_move = pv_info.get("pv", [None])[0]
                        if pv_move == actual_move:
                            actual_score = pv_info["score"].pov(mover_color).score(mate_score=10000)
                            break
                    
                    # If actual move not in top moves, analyze it specifically
                    if actual_score is None:
                        # Push move to analyze resulting position
                        board.push(actual_move)
                        pushed = True
                        
                        # Analyze resulting position
                        # Note: Resulting position is opponent's turn. 
                        # We want score from original mover's perspective.
                        info_after = engine.analyse(board, chess.engine.Limit(depth=depth))
                        actual_score = info_after["score"].pov(mover_color).score(mate_score=10000)
                    
                    # Calculate loss
                    centipawn_loss = best_score - actual_score
                    
                    # Debug log
                    # logger.debug(f"Move: {move_str} | Best: {best_score} | Actual: {actual_score} | Loss: {centipawn_loss}")
                    
                    if centipawn_loss > blunder_threshold_cp:
                        logger.info(f"BLUNDER DETECTED: {move_str} (Loss: {centipawn_loss})")
                        
                        # If we pushed to analyze, pop to get the "before" state FEN
                        if pushed:
                            board.pop()
                            
                        blunder_fen = board.fen()
                        
                        return {
                            "fen": blunder_fen,
                            "blunder_move": actual_move.uci(),
                            "best_move": best_move.uci() if best_move else None,
                            "blunder_score": actual_score / 100.0,
                            "best_score": best_score / 100.0
                        }
                    
                    # Prepare for next iteration
                    if not pushed:
                        board.push(actual_move)
            
            logger.info("Analysis complete: No blunders found.")
            return None
            
        except FileNotFoundError:
            logger.error(f"Stockfish not found at {self.stockfish_path}")
            return None
        except Exception as e:
            logger.error(f"Error analyzing game: {e}")
            return None

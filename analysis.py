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
            game = chess.pgn.read_game(io.StringIO(pgn))
            
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


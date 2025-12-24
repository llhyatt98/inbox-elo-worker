import os
import logging
import resend
import base64
import chess
import chess.svg
import re
from typing import Dict, Any, Optional
from datetime import datetime
from mjml import mjml_to_html

logger = logging.getLogger(__name__)

class EmailService:
    """Service for sending emails using Resend."""
    
    def __init__(self):
        """Initialize the email service with API key from environment."""
        self.api_key = os.getenv('RESEND_API_KEY')
        if not self.api_key:
            logger.warning("RESEND_API_KEY not found in environment variables")
        else:
            resend.api_key = self.api_key
            
        self.from_email = os.getenv('FROM_EMAIL', 'Inbox Elo <team@support.inboxelo.com>')
        self.to_email = os.getenv('TO_EMAIL', 'admin@cognientai.com')

    def _get_formatted_from_email(self) -> str:
        """
        Add today's date to the sender name.
        Example: "Inbox Elo - Dec 19 <team@support.inboxelo.com>"
        """
        try:
            # Parse the configured from_email to separate name and email
            if '<' in self.from_email and '>' in self.from_email:
                name_part, email_part = self.from_email.split('<', 1)
                name_part = name_part.strip()
                email_part = email_part.rstrip('>')
                today_str = datetime.now().strftime("%b %d")

                return f"Inbox Elo ♟️ {today_str} <{email_part}>"
            return self.from_email
        except Exception:
            return self.from_email

    def _get_mjml_template(self, data: Dict[str, Any]) -> str:
        """
        Generate the MJML template for the email analysis.
        
        Args:
            data: Dictionary containing analysis results
            
        Returns:
            MJML string
        """
        username = data.get('username', 'Unknown User')
        status = data.get('status', 'UNKNOWN')
        analysis = data.get('analysis_result')
        pgn = data.get('pgn', '')
        
        # Colors - Google/Frontend Theme
        page_bg = "#F8F9FA"       # Surface
        bg_color = "#FFFFFF"      # Background
        text_primary = "#202124"  # Dark Text / Headers
        text_secondary = "#5F6368" # Body Text
        text_subtle = "#9AA0A6"   # Subtle Text
        
        # Semantic Colors
        color_brand = "#1A73E8"   # Google Blue
        color_error = "#D93025"   # Google Red
        color_success = "#1E8E3E" # Google Green
        
        # Determine theme colors and messages
        opponent = "Unknown Opponent"
        game_date = "Unknown Date"

        if pgn:
            white_match = re.search(r'\[White "(.*?)"\]', pgn)
            black_match = re.search(r'\[Black "(.*?)"\]', pgn)
            date_match = re.search(r'\[Date "(.*?)"\]', pgn)
            
            white = white_match.group(1) if white_match else "Unknown"
            black = black_match.group(1) if black_match else "Unknown"
            
            if username == white:
                opponent = black
            else:
                opponent = white
                
            if date_match:
                game_date = date_match.group(1)

        if status == 'NO_BLUNDER':
            status_color = color_success
            status_title = "Great Game!"
            status_message = f"No significant blunders were detected by the engine in your game against <strong>{opponent}</strong> on <strong>{game_date}</strong>."
        else:
            status_color = color_error
            status_title = "Blunder Alert"
            status_message = f"A critical moment was found in your game against <strong>{opponent}</strong> on <strong>{game_date}</strong>."

        # Build dynamic sections
        analysis_section = ""
        if analysis:
            fen = analysis.get('fen')
            blunder_move = analysis.get('blunder_move')
            best_move = analysis.get('best_move')
            blunder_score = analysis.get('blunder_score', 0.0)
            best_score = analysis.get('best_score', 0.0)
            
            # Generate SVG for Blunder (Player's Move)
            board = chess.Board(fen)
            blunder_move_obj = chess.Move.from_uci(blunder_move)
            
            # Make the blunder move on the board to show the resulting position
            board.push(blunder_move_obj)
            
            # Determine orientation
            orientation = chess.WHITE
            if pgn and f'[Black "{username}"]' in pgn:
                orientation = chess.BLACK
                
            # Configure visual styles
            board_size = 600
            highlight_color = "#b9d3ed80"  # Transparent blue for highlights
            arrow_color = "#D93025"        # Red for blunder
            best_arrow_color = "#1E8E3E"   # Green for best move
            
            # 1. Player's Blunder Board
            # Highlight the squares involved in the blunder move (from -> to)
            fill_blunder = {
                blunder_move_obj.from_square: highlight_color,
                blunder_move_obj.to_square: highlight_color
            }
            
            svg_blunder = chess.svg.board(
                board=board,
                size=board_size,
                orientation=orientation,
                lastmove=blunder_move_obj,
                fill=fill_blunder,
                arrows=[],
                coordinates=True
            )
            svg_blunder = svg_blunder.replace(f'width="{board_size}"', 'width="100%"').replace(f'height="{board_size}"', 'height="auto"')

            # 2. Best Move Board
            # Reset board and make the best move instead
            board.pop() # Undo blunder
            
            best_move_obj = None
            svg_best = ""
            
            if best_move:
                best_move_obj = chess.Move.from_uci(best_move)
                board.push(best_move_obj)
                
                fill_best = {
                    best_move_obj.from_square: highlight_color,
                    best_move_obj.to_square: highlight_color
                }
                
                svg_best = chess.svg.board(
                    board=board, 
                    size=board_size, 
                    orientation=orientation,
                    lastmove=best_move_obj,
                    fill=fill_best,
                    arrows=[],
                    coordinates=True
                )
                svg_best = svg_best.replace(f'width="{board_size}"', 'width="100%"').replace(f'height="{board_size}"', 'height="auto"')
            
            analysis_section = f"""
                    <mj-text padding="0px" align="center">
                        <div style="margin: 0 auto; max-width: 600px; padding-bottom: 10px; padding-left: 10px; padding-right: 10px;" class="board-shadow">
                            {svg_blunder}
                        </div>
                        <p style="color: {text_primary}; font-size: 16px; font-weight: 500; margin-top: 10px; margin-bottom: 5px;">Your Move: <span style="color: {color_error};">{blunder_move}</span></p>
                        <p style="color: {text_secondary}; font-size: 14px; margin-bottom: 30px;">This move resulted in {blunder_score:+.2f}</p>
                    </mj-text>
                    
                    <mj-text padding="0px" align="center">
                        <div style="margin: 0 auto; max-width: 600px; padding-top: 10px; padding-bottom: 10px; padding-left: 10px; padding-right: 10px;" class="board-shadow">
                            {svg_best}
                        </div>
                        <p style="color: {text_primary}; font-size: 16px; font-weight: 500; margin-top: 10px; margin-bottom: 5px;">Best Move: <span style="color: {color_success};">{best_move}</span></p>
                        <p style="color: {text_secondary}; font-size: 14px; margin-bottom: 30px;">The best move would have resulted in {best_score:+.2f}</p>
                    </mj-text>
            """
        elif status == 'NO_BLUNDER':
             analysis_section = f"""
                    <mj-text color="{status_color}" font-size="18px" align="center" line-height="28px">
                        Perfect play! The engine couldn't find any significant improvements.
                    </mj-text>
            """

        return f"""
        <mjml>
            <mj-head>
                <mj-title>Chess Analysis - {username}</mj-title>
                <mj-preview>Analysis results for your recent game vs {username}</mj-preview>
                
                <!-- Force Light Mode -->
                <mj-raw>
                    <meta name="color-scheme" content="light">
                    <meta name="supported-color-schemes" content="light">
                </mj-raw>
                
                <mj-attributes>
                    <mj-all font-family="Roboto, Helvetica, Arial, sans-serif"></mj-all>
                    <mj-text font-weight="400" font-size="16px" color="{text_primary}" line-height="24px"></mj-text>
                    <mj-section padding="0px"></mj-section>
                </mj-attributes>
                <mj-style>
                    @import url('https://fonts.googleapis.com/css?family=Roboto:300,400,500,700|Roboto+Mono:400,500');
                </mj-style>
                <mj-style inline="inline">
                    .board-shadow svg {{
                        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
                        border-radius: 12px;
                        display: block;
                    }}
                    .logo-text {{
                        font-size: 26px;
                        font-weight: 700;
                        color: {text_primary};
                        line-height: 48px;
                        margin-left: 16px;
                        display: inline-block;
                        vertical-align: middle;
                    }}
                    .logo-container {{
                        display: inline-block;
                        vertical-align: middle;
                    }}
                </mj-style>
                <!-- CSS to force light background in dark mode clients -->
                <mj-style>
                    body {{ background-color: {page_bg} !important; }}
                    .mj-body {{ background-color: {page_bg} !important; }}
                </mj-style>
            </mj-head>
            <mj-body background-color="{page_bg}" width="600px">
                
                <!-- Spacer -->
                <mj-section padding="20px 0"></mj-section>
                
                <!-- Main Content Card -->
                <mj-section background-color="{bg_color}" padding="48px 0 40px" border-radius="16px">
                    <mj-column>
                        
                        <mj-text align="center" color="{text_secondary}" font-size="16px" padding-bottom="48px">
                            Analysis for <strong>{username}</strong> — {status_message}
                        </mj-text>

                        <!-- Dynamic Analysis Content -->
                        {analysis_section}

                    </mj-column>
                </mj-section>

                <!-- Footer -->
                <mj-section padding="24px 0 40px">
                    <mj-column>
                        <mj-text align="center" color="{text_subtle}" font-size="12px">
                            © 2024 Inbox Elo. All rights reserved.
                        </mj-text>
                    </mj-column>
                </mj-section>
            </mj-body>
        </mjml>
        """

    def send_analysis_results(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Send an email with the chess analysis results.
        
        Args:
            result: Dictionary containing analysis results (username, pgn, analysis_result, etc.)
            
        Returns:
            The response from Resend API if successful, None otherwise.
        """
        if not self.api_key:
            logger.error("Cannot send email: RESEND_API_KEY not configured")
            return None

        try:
            username = result.get('username', 'Unknown User')
            
            subject = f"Chess Analysis for {username}"
            
            # Generate MJML template
            mjml_content = self._get_mjml_template(result)
            
            # Convert MJML to HTML
            mjml_result = mjml_to_html(mjml_content)
            html_content = mjml_result.html
            
            # logger.info(f"Sending email to {self.to_email} for user {username}")
            
            r = resend.Emails.send({
                "from": self._get_formatted_from_email(),
                "to": self.to_email,
                "subject": subject,
                "html": html_content
            })
            
            logger.info(f"Email sent successfully.")
            return r
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            return None

import os
import logging
import resend
import base64
import chess
import chess.svg
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
            
        self.from_email = os.getenv('FROM_EMAIL', 'Daily Chess Coach <team@support.inboxelo.com>')
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
                # Remove "Daily Chess Coach" if it's there to avoid duplication if user configured it
                if name_part == "Daily Chess Coach":
                    name_part = "Inbox Elo"
                
                email_part = email_part.rstrip('>')
                
                today_str = datetime.now().strftime("%b %d")
                return f"{name_part} ♟️ {today_str} <{email_part}>"
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
        
        # Colors
        bg_color = "#ffffff"
        primary_purple = "#9381ff"
        text_primary = "#1a1a1a"
        text_secondary = "#666666"
        
        # Determine theme colors and messages
        if status == 'NO_BLUNDER':
            status_color = "#10b981" # Soft Emerald Green
            status_title = "Great Game!"
            status_message = "No significant blunders were detected by the engine."
        else:
            status_color = primary_purple # Brand Purple for alert
            status_title = "Blunder Alert"
            status_message = "A critical moment was found in your game."

        # Build dynamic sections
        analysis_section = ""
        if analysis:
            fen = analysis.get('fen')
            blunder_move = analysis.get('blunder_move')
            best_move = analysis.get('best_move')
            
            # Generate SVG using python-chess
            board = chess.Board(fen)
            
            # Determine orientation
            orientation = chess.WHITE
            if pgn and f'[Black "{username}"]' in pgn:
                orientation = chess.BLACK
                
            # Generate SVG
            svg_content = chess.svg.board(board=board, size=600, orientation=orientation)
            svg_content = svg_content.replace('width="600"', 'width="100%"').replace('height="600"', 'height="auto"')
            
            analysis_section = f"""
                    <mj-text padding="0px" align="center">
                        <div style="margin: 0 auto; max-width: 600px; padding-bottom: 30px; padding-left: 10px; padding-right: 10px;" class="board-shadow">
                            {svg_content}
                        </div>
                    </mj-text>
                    
                    <mj-table padding="0 20px">
                        <tr style="border-bottom: 1px solid #b8b8ff;">
                            <td style="padding: 16px 0; color: #666666; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; font-weight: 500;">Your Move</td>
                            <td style="padding: 16px 0; text-align: right; color: #ef4444; font-family: 'Roboto Mono', monospace; font-size: 18px; font-weight: 500;">{blunder_move}</td>
                        </tr>
                        <tr>
                            <td style="padding: 16px 0; color: #666666; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; font-weight: 500;">Best Move</td>
                            <td style="padding: 16px 0; text-align: right; color: #10b981; font-family: 'Roboto Mono', monospace; font-size: 18px; font-weight: 500;">{best_move}</td>
                        </tr>
                    </mj-table>
                    
                    <mj-text padding="0px" align="center">
                        <div style="margin: 0 auto; max-width: 600px; padding-top: 20px; padding-bottom: 30px; padding-left: 10px; padding-right: 10px;" class="board-shadow">
                            {svg_content}
                        </div>
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
                </mj-style>
            </mj-head>
            <mj-body background-color="{bg_color}" width="600px">
                
                <mj-section padding="40px 0 20px">
                    <mj-column>
                        
                        <!-- Status Header -->
                        <mj-text align="center" color="{status_color}" font-size="32px" font-weight="700" padding-bottom="12px" letter-spacing="-1px">
                            {status_title}
                        </mj-text>
                        
                        <mj-text align="center" color="{text_secondary}" font-size="16px" padding-bottom="40px">
                            Analysis for <strong>{username}</strong> — {status_message}
                        </mj-text>

                        <!-- Dynamic Analysis Content -->
                        {analysis_section}

                    </mj-column>
                </mj-section>

                <!-- Footer -->
                <mj-section padding="0 0 40px">
                    <mj-column>
                        <mj-text align="center" color="#9CA3AF" font-size="12px">
                            © 2024 Daily Chess Coach. All rights reserved.
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
            status = result.get('status', 'UNKNOWN')
            
            subject = f"Chess Analysis for {username}: {status}"
            
            # Generate MJML template
            mjml_content = self._get_mjml_template(result)
            
            # Convert MJML to HTML
            mjml_result = mjml_to_html(mjml_content)
            html_content = mjml_result.html
            
            logger.info(f"Sending email to {self.to_email} for user {username}")
            
            r = resend.Emails.send({
                "from": self._get_formatted_from_email(),
                "to": self.to_email,
                "subject": subject,
                "html": html_content
            })
            
            logger.info(f"Email sent successfully. ID: {r.get('id')}")
            return r
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            return None

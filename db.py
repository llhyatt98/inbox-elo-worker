"""
Database connection module for PostgreSQL/Supabase.
Forces IPv4 resolution to avoid Docker IPv6 issues.
"""

import os
import socket
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse, unquote
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_hostname_to_ipv4(hostname: str) -> str:
    """
    Resolve hostname to IPv4 address explicitly.
    This avoids IPv6 resolution issues in Docker containers.
    
    Args:
        hostname: The hostname to resolve
        
    Returns:
        IPv4 address as string
        
    Raises:
        socket.gaierror: If hostname cannot be resolved to IPv4
    """
    try:
        # Force IPv4 resolution
        ipv4 = socket.gethostbyname(hostname)
        logger.debug(f"Resolved {hostname} to IPv4: {ipv4}")
        return ipv4
    except socket.gaierror as e:
        logger.error(f"Failed to resolve {hostname} to IPv4: {e}")
        raise


def get_db_connection():
    """
    Get a database connection using individual environment variables or DATABASE_URL.
    Forces IPv4 resolution to avoid Docker IPv6 issues.
    
    Priority:
    1. Individual environment variables (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT)
    2. DATABASE_URL (parsed and converted to individual parameters)
    
    Returns:
        psycopg2.connection: Database connection object
        
    Raises:
        ValueError: If required parameters are not set
        psycopg2.Error: If connection fails
    """
    # Try individual environment variables first
    hostname = os.getenv('DB_HOST')
    username = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    database = os.getenv('DB_NAME')
    port = os.getenv('DB_PORT', '5432')
    
    # Validate all required parameters
    if not all([hostname, username, password, database]):
        # DEBUGGING: Print what we DO have
        print("--- DEBUG ENV VARS ---")
        print(f"DB_HOST present: {bool(hostname)}")
        print(f"DB_USER present: {bool(username)}")
        print(f"DB_PASSWORD present: {bool(password)}")
        print(f"DB_NAME present: {bool(database)}")
        # print("All Environment Keys:", list(os.environ.keys())) # Uncomment if needed
        print("----------------------")
        raise ValueError("Missing required database connection parameters")
    
    # Resolve hostname to IPv4 explicitly
    ipv4_address = resolve_hostname_to_ipv4(hostname)
    
    # Connect using individual parameters with IPv4 address
    # logger.debug(f"Connecting to {username}@{ipv4_address}:{port}/{database}")
    return psycopg2.connect(
        host=ipv4_address,  # Use IPv4 address instead of hostname
        port=int(port),
        user=username,
        password=password,
        database=database,
        connect_timeout=10
    )

def test_connection() -> bool:
    """
    Test the database connection.
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT NOW();")
                result = cur.fetchone()
                logger.info(f"Database connection successful. Server time: {result[0]}")
                return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


if __name__ == '__main__':
    # Test connection when run directly
    logging.basicConfig(level=logging.INFO)
    test_connection()


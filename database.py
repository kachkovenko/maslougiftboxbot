"""
Database module for Gift Bot
Uses SQLite for data persistence
"""

import sqlite3
import os
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

DATABASE_PATH = os.environ.get("DATABASE_PATH", "gifts.db")


class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_PATH
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database tables"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Gifts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    price INTEGER,
                    category TEXT DEFAULT 'other',
                    status TEXT DEFAULT 'available',
                    added_by_id INTEGER,
                    added_by_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Buyers table (for tracking who's buying what)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS buyers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gift_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT,
                    amount INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (gift_id) REFERENCES gifts(id) ON DELETE CASCADE,
                    UNIQUE(gift_id, user_id)
                )
            """)
            
            # Banned users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT,
                    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Admins table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    
    # ============ GIFT OPERATIONS ============
    
    def add_gift(self, name: str, price: Optional[int], category: str,
                 added_by_id: int, added_by_name: str) -> int:
        """Add a new gift idea"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO gifts (name, price, category, added_by_id, added_by_name)
                VALUES (?, ?, ?, ?, ?)
            """, (name, price, category, added_by_id, added_by_name))
            return cursor.lastrowid
    
    def get_gift(self, gift_id: int) -> Optional[Dict[str, Any]]:
        """Get a single gift by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_gifts(self) -> List[Dict[str, Any]]:
        """Get all gifts"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM gifts 
                ORDER BY 
                    CASE status 
                        WHEN 'available' THEN 1 
                        WHEN 'claimed' THEN 2 
                        WHEN 'bought' THEN 3 
                        WHEN 'already_has' THEN 4 
                    END,
                    category,
                    name
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def update_gift_status(self, gift_id: int, status: str):
        """Update gift status"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE gifts SET status = ? WHERE id = ?",
                (status, gift_id)
            )
    
    def delete_gift(self, gift_id: int):
        """Delete a gift"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Delete buyers first (foreign key)
            cursor.execute("DELETE FROM buyers WHERE gift_id = ?", (gift_id,))
            cursor.execute("DELETE FROM gifts WHERE id = ?", (gift_id,))
    
    # ============ BUYER OPERATIONS ============
    
    def add_buyer(self, gift_id: int, user_id: int, user_name: str,
                  amount: Optional[int] = None):
        """Add a buyer to a gift"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO buyers (gift_id, user_id, user_name, amount)
                VALUES (?, ?, ?, ?)
            """, (gift_id, user_id, user_name, amount))
    
    def update_buyer_amount(self, gift_id: int, user_id: int, amount: int):
        """Update buyer's contribution amount"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE buyers SET amount = ? 
                WHERE gift_id = ? AND user_id = ?
            """, (amount, gift_id, user_id))
    
    def remove_buyer(self, gift_id: int, user_id: int):
        """Remove a buyer from a gift"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM buyers WHERE gift_id = ? AND user_id = ?",
                (gift_id, user_id)
            )
    
    def remove_all_buyers(self, gift_id: int):
        """Remove all buyers from a gift"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM buyers WHERE gift_id = ?", (gift_id,))
    
    def get_gift_buyers(self, gift_id: int) -> List[Dict[str, Any]]:
        """Get all buyers for a gift"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM buyers WHERE gift_id = ?
                ORDER BY created_at
            """, (gift_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_user_gifts(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all gifts a user is buying"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT g.*, b.amount
                FROM gifts g
                JOIN buyers b ON g.id = b.gift_id
                WHERE b.user_id = ?
                ORDER BY g.status, g.name
            """, (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ============ BAN OPERATIONS ============
    
    def ban_user(self, user_id: int, name: str = None):
        """Ban a user (the birthday person)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO banned_users (user_id, name)
                VALUES (?, ?)
            """, (user_id, name))
    
    def unban_user(self, user_id: int):
        """Unban a user"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    
    def is_user_banned(self, user_id: int) -> bool:
        """Check if user is banned"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM banned_users WHERE user_id = ?",
                (user_id,)
            )
            return cursor.fetchone() is not None
    
    def get_banned_users(self) -> List[Dict[str, Any]]:
        """Get list of banned users"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM banned_users")
            return [dict(row) for row in cursor.fetchall()]
    
    # ============ ADMIN OPERATIONS ============
    
    def add_admin(self, user_id: int, name: str = None):
        """Add an admin"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO admins (user_id, name)
                VALUES (?, ?)
            """, (user_id, name))
    
    def remove_admin(self, user_id: int):
        """Remove an admin"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
            return cursor.fetchone() is not None
    
    def has_any_admin(self) -> bool:
        """Check if there's at least one admin"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM admins LIMIT 1")
            return cursor.fetchone() is not None
    
    def get_admins(self) -> List[Dict[str, Any]]:
        """Get list of admins"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM admins")
            return [dict(row) for row in cursor.fetchall()]
    
    # ============ STATISTICS ============
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Gift counts by status
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END) as available,
                    SUM(CASE WHEN status = 'claimed' THEN 1 ELSE 0 END) as claimed,
                    SUM(CASE WHEN status = 'bought' THEN 1 ELSE 0 END) as bought,
                    SUM(CASE WHEN status = 'already_has' THEN 1 ELSE 0 END) as already_has
                FROM gifts
            """)
            row = cursor.fetchone()
            
            # Unique participants
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM buyers")
            participants = cursor.fetchone()[0]
            
            # Total amount pledged
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM buyers")
            total_amount = cursor.fetchone()[0]
            
            return {
                'total': row['total'] or 0,
                'available': row['available'] or 0,
                'claimed': row['claimed'] or 0,
                'bought': row['bought'] or 0,
                'already_has': row['already_has'] or 0,
                'participants': participants or 0,
                'total_amount': total_amount or 0
            }

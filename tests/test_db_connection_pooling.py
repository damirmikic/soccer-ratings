import unittest
from unittest import mock
import os

from soccer_ratings import db

class DBConnectionPoolingTests(unittest.TestCase):
    def setUp(self):
        # Save real pool state
        self._real_pool = db._POOL
        db._POOL = None

    def tearDown(self):
        # Restore real pool state
        db._POOL = self._real_pool

    @mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost:5432/db"})
    @mock.patch("psycopg_pool.ConnectionPool")
    def test_init_pool_creates_connection_pool(self, mock_pool_class):
        db.init_pool(min_size=2, max_size=5)
        self.assertIsNotNone(db._POOL)
        mock_pool_class.assert_called_once_with(
            "postgresql://user:pass@localhost:5432/db",
            min_size=2,
            max_size=5,
            open=True
        )

    def test_close_pool_closes_and_cleans_up(self):
        mock_pool = mock.Mock()
        db._POOL = mock_pool
        db.close_pool()
        mock_pool.close.assert_called_once()
        self.assertIsNone(db._POOL)

    @mock.patch("soccer_ratings.db.connect")
    def test_db_cursor_falls_back_when_no_pool(self, mock_connect):
        # Mock connection and cursor context managers
        mock_conn = mock_connect.return_value.__enter__.return_value
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value

        with db.db_cursor(use_direct=False) as (conn, cur):
            self.assertEqual(conn, mock_conn)
            self.assertEqual(cur, mock_cur)

        mock_connect.assert_called_once()

    def test_db_cursor_uses_pool_when_available(self):
        mock_pool = mock.MagicMock()
        db._POOL = mock_pool

        mock_conn = mock_pool.connection.return_value.__enter__.return_value
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value

        with db.db_cursor(use_direct=False) as (conn, cur):
            self.assertEqual(conn, mock_conn)
            self.assertEqual(cur, mock_cur)

        mock_pool.connection.assert_called_once()
        mock_conn.cursor.assert_called_once()

    @mock.patch("soccer_ratings.db.connect")
    def test_db_cursor_uses_direct_connection_even_if_pool_available(self, mock_connect):
        mock_pool = mock.MagicMock()
        db._POOL = mock_pool

        mock_conn = mock_connect.return_value.__enter__.return_value
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value

        with db.db_cursor(use_direct=True) as (conn, cur):
            self.assertEqual(conn, mock_conn)
            self.assertEqual(cur, mock_cur)

        mock_pool.connection.assert_not_called()
        mock_connect.assert_called_once_with(None, use_direct=True)

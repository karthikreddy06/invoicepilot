import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional
from app.config import settings


@contextmanager
def get_db_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite database connection, ensuring proper close."""
    path = db_path or settings.DB_PATH
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables, columns, and indexes."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paypal_invoice_id TEXT UNIQUE NOT NULL,
                client_email TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                due_date TEXT,
                created_at TEXT NOT NULL,
                paid_at TEXT,
                is_simulated INTEGER DEFAULT 0
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                message TEXT NOT NULL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_paypal_id ON invoices(paypal_invoice_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_invoice_id ON reminders(invoice_id);")

        # Graceful migration for existing databases missing is_simulated
        try:
            cursor.execute("ALTER TABLE invoices ADD COLUMN is_simulated INTEGER DEFAULT 0;")
        except sqlite3.OperationalError:
            pass

        conn.commit()


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def upsert_invoice(
    paypal_invoice_id: str,
    client_email: str,
    description: str,
    amount: float,
    status: str,
    due_date: Optional[str] = None,
    created_at: Optional[str] = None,
    paid_at: Optional[str] = None,
    is_simulated: int = 0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert or update an invoice in the database."""
    now_iso = datetime.now(timezone.utc).isoformat()
    c_at = created_at or now_iso

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO invoices (
                paypal_invoice_id, client_email, description, amount, status, due_date, created_at, paid_at, is_simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paypal_invoice_id) DO UPDATE SET
                client_email = excluded.client_email,
                description = excluded.description,
                amount = excluded.amount,
                status = excluded.status,
                due_date = COALESCE(excluded.due_date, invoices.due_date),
                paid_at = COALESCE(excluded.paid_at, invoices.paid_at),
                is_simulated = excluded.is_simulated;
        """, (paypal_invoice_id, client_email, description, amount, status, due_date, c_at, paid_at, is_simulated))
        conn.commit()

    return get_invoice_by_paypal_id(paypal_invoice_id, db_path=db_path)


def update_invoice_status(
    paypal_invoice_id: str,
    status: str,
    paid_at: Optional[str] = None,
    is_simulated: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update invoice status, paid_at timestamp, and optional is_simulated flag."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        clauses = ["status = ?"]
        params: List[Any] = [status]

        if paid_at is not None:
            clauses.append("paid_at = ?")
            params.append(paid_at)

        if is_simulated is not None:
            clauses.append("is_simulated = ?")
            params.append(is_simulated)

        params.append(paypal_invoice_id)
        sql = f"UPDATE invoices SET {', '.join(clauses)} WHERE paypal_invoice_id = ?"
        cursor.execute(sql, tuple(params))
        conn.commit()

    return get_invoice_by_paypal_id(paypal_invoice_id, db_path=db_path)


def get_invoice_by_paypal_id(
    paypal_invoice_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Get single invoice by PayPal ID including its reminder count."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM invoices WHERE paypal_invoice_id = ?", (paypal_invoice_id,))
        row = cursor.fetchone()
        if not row:
            return None
        res = row_to_dict(row)

        cursor.execute("SELECT COUNT(*) as count FROM reminders WHERE invoice_id = ?", (paypal_invoice_id,))
        cnt_row = cursor.fetchone()
        res["reminder_count"] = cnt_row["count"] if cnt_row else 0
        return res


def get_all_invoices(
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get all invoices, optionally filtered by status, ordered by created_at DESC."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM invoices WHERE UPPER(status) = UPPER(?) ORDER BY id DESC",
                (status,),
            )
        else:
            cursor.execute("SELECT * FROM invoices ORDER BY id DESC")
        rows = cursor.fetchall()
        results = []
        for r in rows:
            item = row_to_dict(r)
            cursor.execute("SELECT COUNT(*) as count FROM reminders WHERE invoice_id = ?", (item["paypal_invoice_id"],))
            cnt_row = cursor.fetchone()
            item["reminder_count"] = cnt_row["count"] if cnt_row else 0
            results.append(item)
        return results


def get_non_final_invoices(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all active invoices that are not in a final PayPal state (PAID, CANCELLED, REFUNDED).
    These need periodic reconciliation with PayPal's live status.
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM invoices
            WHERE UPPER(status) IN ('SENT', 'UNPAID', 'DRAFT', 'PARTIALLY_PAID', 'SCHEDULED')
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        results = []
        for r in rows:
            item = row_to_dict(r)
            cursor.execute("SELECT COUNT(*) as count FROM reminders WHERE invoice_id = ?", (item["paypal_invoice_id"],))
            cnt_row = cursor.fetchone()
            item["reminder_count"] = cnt_row["count"] if cnt_row else 0
            results.append(item)
        return results


def clear_all_data(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Clear all records from reminders and invoices tables."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminders;")
        cursor.execute("DELETE FROM invoices;")
        conn.commit()
    return {"success": True, "message": "All invoices and reminders cleared."}


def record_reminder(
    invoice_id: str,
    message: str,
    sent_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a sent reminder message in the database."""
    now_iso = sent_at or datetime.now(timezone.utc).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (invoice_id, sent_at, message) VALUES (?, ?, ?)",
            (invoice_id, now_iso, message),
        )
        rem_id = cursor.lastrowid
        conn.commit()

        cursor.execute("SELECT * FROM reminders WHERE id = ?", (rem_id,))
        return row_to_dict(cursor.fetchone())


def get_reminders_for_invoice(
    invoice_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch all reminders sent for a given invoice."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM reminders WHERE invoice_id = ? ORDER BY id ASC",
            (invoice_id,),
        )
        return [row_to_dict(r) for r in cursor.fetchall()]


def get_reminder_count(
    invoice_id: str,
    db_path: Optional[str] = None,
) -> int:
    """Fetch total count of reminders sent for an invoice."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM reminders WHERE invoice_id = ?", (invoice_id,))
        row = cursor.fetchone()
        return row["count"] if row else 0


def get_unpaid_invoices(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all invoices with unpaid status (SENT, DRAFT, UNPAID, PARTIALLY_PAID)."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM invoices
            WHERE UPPER(status) IN ('SENT', 'UNPAID', 'PARTIALLY_PAID')
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        results = []
        for r in rows:
            item = row_to_dict(r)
            cursor.execute("SELECT COUNT(*) as count FROM reminders WHERE invoice_id = ?", (item["paypal_invoice_id"],))
            cnt_row = cursor.fetchone()
            item["reminder_count"] = cnt_row["count"] if cnt_row else 0
            results.append(item)
        return results

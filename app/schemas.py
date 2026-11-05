from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class InvoiceBase(BaseModel):
    client_email: str
    description: str
    amount: float = Field(gt=0, description="Amount in USD")
    due_date: Optional[str] = None


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceDB(InvoiceBase):
    id: Optional[int] = None
    paypal_invoice_id: str
    status: str = "DRAFT"
    created_at: str
    paid_at: Optional[str] = None
    reminder_count: int = 0


class ReminderDB(BaseModel):
    id: Optional[int] = None
    invoice_id: str
    sent_at: str
    message: str


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str


class ChatResponse(BaseModel):
    reply: str
    actions_taken: List[Dict[str, Any]] = []


class HealthResponse(BaseModel):
    status: str
    paypal_connected: bool
    database: str
    demo_mode: bool


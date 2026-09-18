from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class StockCatalogSync(Base):
    """Single-row (``id=1``) bookkeeping for the local A-share stock catalog.

    V2 search answers from MySQL instead of fetching the whole market snapshot
    per request, so operators need to know whether the catalog is actually
    complete and when it was last refreshed successfully. A failed sync must
    never look like a successful one, which is why ``last_success_at`` is only
    written after a validated sync.
    """

    __tablename__ = "stock_catalog_sync"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[Optional[str]] = mapped_column(String(200))
    last_error: Mapped[Optional[str]] = mapped_column(String(500))

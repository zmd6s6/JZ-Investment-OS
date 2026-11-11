"""Locked bounded traversal progress, independent of daily authorization and business history."""

from uuid import UUID

from sqlalchemy import Select, text
from sqlalchemy.ext.asyncio import AsyncSession


async def scan_ids(
    session: AsyncSession, kind: str, statement: Select[tuple[UUID]]
) -> tuple[UUID, ...]:
    await session.execute(
        text(
            "INSERT INTO daily_scan_cursor (kind, after_id) VALUES (:kind, NULL) "
            "ON CONFLICT (kind) DO NOTHING"
        ),
        {"kind": kind},
    )
    after = await session.scalar(
        text("SELECT after_id FROM daily_scan_cursor WHERE kind = :kind FOR UPDATE"),
        {"kind": kind},
    )
    identifier = statement.selected_columns[0]
    following = statement.where(identifier > after) if after is not None else statement
    rows = tuple((await session.scalars(following.order_by(identifier).limit(50))).all())
    if not rows and after is not None:
        rows = tuple((await session.scalars(statement.order_by(identifier).limit(50))).all())
    return rows


async def advance_scan(session: AsyncSession, kind: str, after: UUID | None) -> None:
    await session.execute(
        text("UPDATE daily_scan_cursor SET after_id = :after WHERE kind = :kind"),
        {"after": after, "kind": kind},
    )

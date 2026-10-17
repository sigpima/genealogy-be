"""Bài đệm / tự bối: the word the clan gives each generation. Replaced as a whole by an admin."""

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.permissions import get_read_context, get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.article import GenerationWord
from app.schemas.chronicles import WordOut, WordsIn

router = APIRouter(prefix="/generation-poem", tags=["generation words"])


async def _words(db: AsyncSession, tree_id: int) -> list[WordOut]:
    rows = (await db.execute(select(GenerationWord).where(GenerationWord.tree_id == tree_id).order_by(GenerationWord.generation))).scalars().all()
    return [WordOut(generation=r.generation, word=r.word, meaning=r.meaning) for r in rows]


@router.get("", response_model=list[WordOut])
async def get_words(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)) -> list[WordOut]:
    return await _words(db, ctx.tree.id)


@router.put("", response_model=list[WordOut])
async def put_words(payload: WordsIn, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> list[WordOut]:
    before = {w.generation: w.word for w in await _words(db, ctx.tree.id)}
    await db.execute(delete(GenerationWord).where(GenerationWord.tree_id == ctx.tree.id))
    db.add_all([GenerationWord(tree_id=ctx.tree.id, generation=w.generation, word=w.word, meaning=w.meaning) for w in payload.words])
    after = {w.generation: w.word for w in payload.words}
    changes = audit.diff_values({f"đời {g}": w for g, w in before.items()}, {f"đời {g}": w for g, w in after.items()})
    if changes:
        audit.record(db, tree_id=ctx.tree.id, actor=ctx.user, action="poem.update", changes=changes)
    await db.commit()
    return await _words(db, ctx.tree.id)

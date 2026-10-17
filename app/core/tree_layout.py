"""One tree's people in memory: depth-first order, generation, branch, spouses.

A family has hundreds to a few thousand people, so the data-entry table, search and statistics all load the tree
once and work on it here instead of writing recursive SQL. Spouses are not part of the blood line: they are listed
separately and take their partner's generation and branch.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branch import Branch
from app.models.marriage import Marriage
from app.models.member import Member

LIVING_MAX_AGE_YEARS = 100  # the same rule as the web app's `memberStatus`


def member_status(birth_year: int | None, death_year: int | None, this_year: int) -> str:
    if death_year is not None:
        return "deceased"
    if birth_year is None:
        return "unknown"
    return "living" if this_year - birth_year <= LIVING_MAX_AGE_YEARS else "unknown"


class TreeLayout:
    def __init__(
        self,
        members: list[Member],
        spouse_ids: set[int],
        partner_of: dict[int, int] | None = None,
        branch_heads: dict[int, int] | None = None,
    ) -> None:
        self.by_id = {m.id: m for m in members}
        self.partner_of = partner_of or {}  # spouse member id -> the blood member they married
        self.children: dict[int | None, list[Member]] = {}
        for member in members:
            if member.id not in spouse_ids:
                self.children.setdefault(member.parent_id, []).append(member)
        for siblings in self.children.values():
            siblings.sort(key=lambda m: (m.birth_order is None, m.birth_order or 0, m.id))
        heads = branch_heads or {}  # head member id -> branch id
        self.order: list[Member] = []
        self.generation: dict[int, int] = {}
        self.branch_of: dict[int, int | None] = {}  # blood member id -> deepest branch id
        stack = [(m, 1, None) for m in reversed(self.children.get(None, []))]
        while stack:
            member, generation, branch = stack.pop()
            branch = heads.get(member.id, branch)
            self.order.append(member)
            self.generation[member.id] = generation
            self.branch_of[member.id] = branch
            stack.extend((c, generation + 1, branch) for c in reversed(self.children.get(member.id, [])))
        self.spouses = [m for m in members if m.id in spouse_ids and m.id in self.partner_of]

    def subtree_ids(self, root_id: int) -> set[int]:
        found, pending = set(), [root_id]
        while pending:
            current = pending.pop()
            found.add(current)
            pending.extend(child.id for child in self.children.get(current, []))
        return found

    def generation_of(self, member_id: int) -> int | None:
        """A spouse counts as the generation of their partner."""
        return self.generation.get(self.partner_of.get(member_id, member_id))

    def branch_id_of(self, member_id: int) -> int | None:
        return self.branch_of.get(self.partner_of.get(member_id, member_id))


async def load_branches(db: AsyncSession, tree_id: int) -> list[Branch]:
    return list((await db.execute(select(Branch).where(Branch.tree_id == tree_id).order_by(Branch.id))).scalars().all())


async def load_layout(db: AsyncSession, tree_id: int, branches: list[Branch] | None = None) -> TreeLayout:
    members = list((await db.execute(select(Member).where(Member.tree_id == tree_id))).scalars().all())
    ids = [m.id for m in members]
    pairs = (
        await db.execute(
            select(Marriage.member_id, Marriage.spouse_id).where(Marriage.member_id.in_(ids)).order_by(Marriage.id)
        )
    ).all()
    partner_of: dict[int, int] = {}
    for member_id, spouse_id in pairs:
        partner_of.setdefault(spouse_id, member_id)
    if branches is None:
        branches = await load_branches(db, tree_id)
    heads = {b.root_member_id: b.id for b in branches}
    return TreeLayout(members, set(partner_of), partner_of, heads)


async def deepest_branch(db: AsyncSession, member: Member, branches: list[Branch]) -> Branch | None:
    """The member's branch without loading the whole tree: walk up until a branch head is met."""
    heads = {b.root_member_id: b for b in branches}
    if not heads:
        return None
    current: Member | None = member
    while current is not None:
        if current.id in heads:
            return heads[current.id]
        current = await db.get(Member, current.parent_id) if current.parent_id is not None else None
    return None

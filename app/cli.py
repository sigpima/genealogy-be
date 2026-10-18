"""Command-line administration (the superadmin web page /he-thong covers the common cases; use this for scripting
and for granting `superadmin`, which the web UI deliberately cannot do).

    uv run python scripts/manage.py create-tree --name "Nguyễn Tộc" --slug nguyen-toc
    uv run python scripts/manage.py create-user --email a@x.com --name "A" --role admin --tree nguyen-toc
    uv run python scripts/manage.py set-role --email a@x.com --role superadmin
    uv run python scripts/manage.py set-password --email a@x.com        # generates and prints one
    uv run python scripts/manage.py list
"""

import argparse
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import ROLES
from app.core.security import hash_password
from app.core.tenants import (
    TenantError,
    create_tree,
    create_user,
    get_tree_by_slug,
    rename_tree,
    set_user_role,
)
from app.models.tree import Tree
from app.models.user import User


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # raise instead of exiting, so run() can report it
        raise TenantError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="manage.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    tree = sub.add_parser("create-tree", help="create a family tree")
    tree.add_argument("--name", required=True)
    tree.add_argument("--slug", required=True, help="lowercase letters/digits and hyphens, used in /t/<slug>")

    rename = sub.add_parser("rename-tree", help="change a tree's name and/or slug")
    rename.add_argument("--slug", required=True, help="the current slug")
    rename.add_argument("--name")
    rename.add_argument("--new-slug")

    user = sub.add_parser("create-user", help="create an active user")
    user.add_argument("--email", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--role", required=True, choices=ROLES)
    user.add_argument("--tree", help="tree slug (required unless the role is superadmin)")
    user.add_argument("--password", help="omit to generate one (it is then printed once)")

    role = sub.add_parser("set-role", help="change a user's role (and tree)")
    role.add_argument("--email", required=True)
    role.add_argument("--role", required=True, choices=ROLES)
    role.add_argument("--tree", help="tree slug (required unless the role is superadmin)")

    pw = sub.add_parser("set-password", help="set a user's password (the way back in for a forgotten superadmin password)")
    pw.add_argument("--email", required=True)
    pw.add_argument("--password", help="omit to generate one (it is then printed once)")

    sub.add_parser("list", help="list trees and users")
    return parser


async def _tree_arg(db: AsyncSession, slug: str | None) -> Tree | None:
    if slug is None:
        return None
    tree = await get_tree_by_slug(db, slug)
    if tree is None:
        raise TenantError(f"no tree with slug {slug!r}")
    return tree


async def run(argv: list[str], db: AsyncSession) -> str:
    """Run one command and return what to print. Mistakes come back as 'error: ...', never a traceback."""
    try:
        args = _build_parser().parse_args(argv)
        if args.command == "create-tree":
            tree = await create_tree(db, args.name, args.slug)
            return f"created tree #{tree.id} {tree.name!r} (slug {tree.slug}); family link: /t/{tree.slug}"
        if args.command == "rename-tree":
            tree = await rename_tree(db, args.slug, name=args.name, new_slug=args.new_slug)
            return f"tree #{tree.id} is now {tree.name!r} (slug {tree.slug})"
        if args.command == "create-user":
            tree = await _tree_arg(db, args.tree)
            password = args.password or secrets.token_urlsafe(12)
            user = await create_user(
                db, email=args.email, full_name=args.name, password=password, role=args.role, tree=tree
            )
            lines = [f"created {user.role} {user.email}" + (f" in tree {tree.slug}" if tree else " (platform level)")]
            if not args.password:
                lines.append(f"password: {password}")
            return "\n".join(lines)
        if args.command == "set-role":
            tree = await _tree_arg(db, args.tree)
            user = await set_user_role(db, args.email, args.role, tree)
            return f"{user.email} is now {user.role}" + (f" of tree {tree.slug}" if tree else " (platform level)")
        if args.command == "set-password":
            user = (await db.execute(select(User).where(User.email == args.email))).scalar_one_or_none()
            if user is None:
                raise TenantError(f"no user with email {args.email!r}")
            if args.password is not None and len(args.password) < 8:
                raise TenantError("password must be at least 8 characters")
            password = args.password or secrets.token_urlsafe(12)
            user.hashed_password = hash_password(password)
            await db.commit()
            if args.password:
                return f"password of {user.email} changed"
            return f"password of {user.email} changed\npassword: {password}"
        trees = (await db.execute(select(Tree).order_by(Tree.id))).scalars().all()
        users = (await db.execute(select(User).order_by(User.id))).scalars().all()
        slug_of = {t.id: t.slug for t in trees}
        lines = ["trees:"] + [f"  #{t.id} {t.slug}  {t.name}" for t in trees]
        lines += ["users:"] + [
            f"  #{u.id} {u.email}  {u.role}/{u.status}  tree={slug_of.get(u.tree_id, '-')}" for u in users
        ]
        return "\n".join(lines)
    except TenantError as exc:
        await db.rollback()
        return f"error: {exc}"

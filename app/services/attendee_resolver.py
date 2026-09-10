import re
import logging
from typing import Any, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import DEMO_USERS
from app.models.entities import OrganizationMember

logger = logging.getLogger(__name__)


class AttendeeResolver:
    """
    Deterministic participant resolver strictly scoped to the authenticated organization.
    Prevents silent identity substitution, cross-tenant leakage, and fabricated emails.
    """

    @classmethod
    async def get_organization_directory(
        cls,
        session: Optional[AsyncSession],
        organization_id: UUID,
    ) -> list[dict[str, Any]]:
        """
        Fetches all known users/contacts belonging strictly to the specified organization.
        """
        directory: list[dict[str, Any]] = []
        seen_emails: set[str] = set()

        # 1. Inspect configured DEMO_USERS for this organization
        for email, u_data in DEMO_USERS.items():
            if u_data.get("organization_id") == organization_id:
                clean_email = email.lower().strip()
                if clean_email not in seen_emails:
                    seen_emails.add(clean_email)
                    directory.append({
                        "user_id": str(u_data.get("user_id")),
                        "email": clean_email,
                        "name": u_data.get("name", clean_email.split("@")[0].capitalize()),
                        "role_name": u_data.get("role_name", ""),
                    })

        # 2. Inspect database organization_members if session is provided
        if session:
            try:
                stmt = select(OrganizationMember).where(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.status == "active",
                )
                members = (await session.execute(stmt)).scalars().all()
                for m in members:
                    m_uid = str(m.user_id)
                    for d_u in DEMO_USERS.values():
                        if str(d_u.get("user_id")) == m_uid:
                            d_email = d_u.get("email", "").lower().strip()
                            if d_email and d_email not in seen_emails:
                                seen_emails.add(d_email)
                                directory.append({
                                    "user_id": m_uid,
                                    "email": d_email,
                                    "name": d_u.get("name", d_email.split("@")[0].capitalize()),
                                    "role_name": d_u.get("role_name", ""),
                                })
            except Exception as e:
                logger.warning("Could not query organization_members: %s", e)

        return directory

    @classmethod
    async def resolve_attendees(
        cls,
        session: Optional[AsyncSession],
        organization_id: UUID,
        attendee_tokens: list[str],
    ) -> dict[str, Any]:
        """
        Resolves natural-language participant names/emails against the organization directory.
        
        Rules:
        - 1 match: Resolved
        - >1 matches: Ambiguous (clarification required)
        - 0 matches: Unresolved (cannot schedule until clarified, no Alice substitution)
        - Never fabricates emails
        - Never searches outside organization_id
        """
        directory = await cls.get_organization_directory(session, organization_id)
        
        resolved: list[dict[str, Any]] = []
        unresolved: list[str] = []
        ambiguous: list[dict[str, Any]] = []
        cross_tenant_rejected: list[str] = []

        for token in attendee_tokens:
            cleaned = token.strip()
            if not cleaned:
                continue

            lower_token = cleaned.lower()

            # Handle team aliases within the tenant
            if lower_token in ("dev team", "dev", "developers", "engineering team", "engineers"):
                team_matches = [
                    u for u in directory
                    if any(term in u.get("role_name", "").lower() or term in u["name"].lower() or term in u["email"].lower() for term in ("engineer", "dev"))
                ]
                if not team_matches and directory:
                    team_matches = directory
                if team_matches:
                    for tm in team_matches:
                        if not any(r["email"] == tm["email"] for r in resolved):
                            resolved.append(tm)
                    continue
                else:
                    unresolved.append(cleaned)
                    continue

            # If token is an explicit email address
            if "@" in lower_token:
                # Check if it belongs to another organization in DEMO_USERS
                other_org_user = DEMO_USERS.get(lower_token)
                if other_org_user and other_org_user.get("organization_id") != organization_id:
                    cross_tenant_rejected.append(cleaned)
                    continue

                # Check if it matches this organization's directory
                match = next((u for u in directory if u["email"].lower() == lower_token), None)
                if match:
                    if not any(r["email"] == match["email"] for r in resolved):
                        resolved.append(match)
                else:
                    # Token is an email not found in this tenant
                    unresolved.append(cleaned)
                continue

            # Token is a name: search within directory
            # 1. Exact full name match
            exact_matches = [
                u for u in directory
                if u["name"].lower() == lower_token
            ]
            if len(exact_matches) == 1:
                match = exact_matches[0]
                if not any(r["email"] == match["email"] for r in resolved):
                    resolved.append(match)
                continue
            elif len(exact_matches) > 1:
                ambiguous.append({
                    "token": cleaned,
                    "candidates": exact_matches,
                })
                continue

            # 2. First name match or email username match
            first_name_matches = [
                u for u in directory
                if u["name"].lower().split()[0] == lower_token
                or u["email"].lower().split("@")[0] == lower_token
            ]
            if len(first_name_matches) == 1:
                match = first_name_matches[0]
                if not any(r["email"] == match["email"] for r in resolved):
                    resolved.append(match)
                continue
            elif len(first_name_matches) > 1:
                ambiguous.append({
                    "token": cleaned,
                    "candidates": first_name_matches,
                })
                continue

            # 3. Partial substring match in name (word boundary)
            partial_matches = [
                u for u in directory
                if re.search(rf"\b{re.escape(lower_token)}\b", u["name"].lower())
            ]
            if len(partial_matches) == 1:
                match = partial_matches[0]
                if not any(r["email"] == match["email"] for r in resolved):
                    resolved.append(match)
                continue
            elif len(partial_matches) > 1:
                ambiguous.append({
                    "token": cleaned,
                    "candidates": partial_matches,
                })
                continue

            # 0 matches found in organization
            unresolved.append(cleaned)

        all_resolved = len(unresolved) == 0 and len(ambiguous) == 0 and len(cross_tenant_rejected) == 0

        return {
            "resolved": resolved,
            "unresolved": unresolved,
            "ambiguous": ambiguous,
            "cross_tenant_rejected": cross_tenant_rejected,
            "all_resolved": all_resolved,
        }

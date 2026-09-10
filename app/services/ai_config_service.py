import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_token, encrypt_token
from app.models.entities import AuditLog, TenantAIConfig

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = {'google_gemini', 'openai', 'anthropic'}


class AIConfigService:
    @staticmethod
    def _create_fingerprint(plain_key: str) -> str:
        clean = plain_key.strip()
        if len(clean) >= 8:
            return f'****{clean[-4:]}'
        return '****'

    @classmethod
    async def get_config(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        provider: str = 'google_gemini',
    ) -> Optional[dict[str, Any]]:
        stmt = select(TenantAIConfig).where(
            TenantAIConfig.organization_id == organization_id,
            TenantAIConfig.provider == provider,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return None

        return {
            'id': str(row.id),
            'organization_id': str(row.organization_id),
            'provider': row.provider,
            'key_fingerprint': row.key_fingerprint,
            'status': row.status,
            'last_verified_at': row.last_verified_at.isoformat() if row.last_verified_at else None,
            'updated_at': row.updated_at.isoformat() if row.updated_at else None,
        }

    @classmethod
    async def list_configs(
        cls,
        session: AsyncSession,
        organization_id: UUID,
    ) -> list[dict[str, Any]]:
        stmt = select(TenantAIConfig).where(TenantAIConfig.organization_id == organization_id)
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                'id': str(row.id),
                'organization_id': str(row.organization_id),
                'provider': row.provider,
                'key_fingerprint': row.key_fingerprint,
                'masked_key': row.key_fingerprint,
                'status': row.status,
                'last_verified_at': row.last_verified_at.isoformat() if row.last_verified_at else None,
                'updated_at': row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]

    @classmethod
    async def get_decrypted_key(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        provider: str = 'google_gemini',
    ) -> Optional[str]:
        stmt = select(TenantAIConfig).where(
            TenantAIConfig.organization_id == organization_id,
            TenantAIConfig.provider == provider,
            TenantAIConfig.status == 'connected',
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row or not row.encrypted_api_key:
            return None

        try:
            return decrypt_token(row.encrypted_api_key)
        except Exception as e:
            logger.error('Failed to decrypt tenant AI API key for org %s: %s', organization_id, e)
            return None

    @classmethod
    async def save_config(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        provider: str,
        api_key: str,
    ) -> dict[str, Any]:
        clean_key = api_key.strip()
        clean_provider = provider.lower().strip()

        if clean_provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Unsupported AI provider. Supported providers: google_gemini, openai, anthropic.',
            )

        if len(clean_key) < 15:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='API key is too short. Please provide a valid API key.',
            )

        encrypted = encrypt_token(clean_key)
        fingerprint = cls._create_fingerprint(clean_key)
        now = datetime.now(timezone.utc)

        stmt = select(TenantAIConfig).where(
            TenantAIConfig.organization_id == organization_id,
            TenantAIConfig.provider == clean_provider,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.encrypted_api_key = encrypted
            existing.key_fingerprint = fingerprint
            existing.status = 'connected'
            existing.last_verified_at = now
            existing.updated_at = now
            existing.updated_by = user_id
            config_id = existing.id
        else:
            config_id = uuid4()
            new_conf = TenantAIConfig(
                id=config_id,
                organization_id=organization_id,
                provider=clean_provider,
                encrypted_api_key=encrypted,
                key_fingerprint=fingerprint,
                status='connected',
                last_verified_at=now,
                created_at=now,
                updated_at=now,
                created_by=user_id,
                updated_by=user_id,
            )
            session.add(new_conf)

        audit = AuditLog(
            id=uuid4(),
            organization_id=organization_id,
            actor_id=user_id,
            actor_type='user',
            action='UPDATE_AI_CONFIG',
            target_entity='tenant_ai_configs',
            target_id=config_id,
            before_state={'provider': clean_provider},
            after_state={'provider': clean_provider, 'fingerprint': fingerprint, 'status': 'connected'},
            result='SUCCESS',
        )
        session.add(audit)
        await session.commit()

        logger.info(
            'Tenant %s updated AI config for provider %s with fingerprint %s (actor: %s)',
            organization_id,
            clean_provider,
            fingerprint,
            user_id,
        )

        return {
            'id': str(config_id),
            'organization_id': str(organization_id),
            'provider': clean_provider,
            'key_fingerprint': fingerprint,
            'status': 'connected',
            'last_verified_at': now.isoformat(),
        }

    @classmethod
    async def delete_config(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        provider: str = 'google_gemini',
    ) -> bool:
        stmt = select(TenantAIConfig).where(
            TenantAIConfig.organization_id == organization_id,
            TenantAIConfig.provider == provider,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return False

        await session.delete(row)

        audit = AuditLog(
            id=uuid4(),
            organization_id=organization_id,
            actor_id=user_id,
            actor_type='user',
            action='DELETE_AI_CONFIG',
            target_entity='tenant_ai_configs',
            target_id=row.id,
            before_state={'provider': provider, 'fingerprint': row.key_fingerprint},
            after_state={'status': 'deleted'},
            result='SUCCESS',
        )
        session.add(audit)
        await session.commit()
        return True

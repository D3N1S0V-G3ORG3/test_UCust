"""
File: ai/api/dependencies/auth.py
Модуль JWT авторизации и извлечения tenant_id.
"""

from __future__ import annotations

import os
import logging
try:
    import jwt
except ImportError:
    jwt = None

from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("AuthGuard")

security = HTTPBearer(auto_error=True)
JWT_SECRET = os.getenv("JWT_SECRET", "ucust_super_secret_jwt_key_2026_production_safe_32b")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


async def get_current_tenant(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """
    Валидирует JWT токен и возвращает tenant_id.
    Блокирует запрос с 401 UNAUTHORIZED при невалидном или просроченном токене.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        tenant_id = payload.get("tenant_id") or payload.get("sub")
        
        if not tenant_id:
            raise ValueError("В токене отсутствует tenant_id или sub")
            
        return str(tenant_id)
    except jwt.ExpiredSignatureError:
        logger.warning("🚫 Токен авторизации просрочен")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Срок действия токена истек",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (jwt.PyJWTError, ValueError) as e:
        logger.warning(f"🚫 Ошибка JWT валидации: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен авторизации",
            headers={"WWW-Authenticate": "Bearer"},
        )

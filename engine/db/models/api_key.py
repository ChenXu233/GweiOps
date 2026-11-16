# engine/db/models/api_key.py
"""密钥 —— 给外界的 agent 用的凭据。

环境变量里的控制台令牌是"部署那一刻"的凭据:写死在 .env 里,换一次要重启,
而且一个部署里只有几条。外界的 agent 不是这个形状——它们一个客户端一把,
要能单独吊销、各自带不同的权限。

所以密钥是库里的对象:有名字(给人看是哪一把)、有权限集(它能看到哪些工具)、
有可选择工具白名单(再收窄一点)、有前缀(认得出来,但换不回明文)。
明文只在签发那一次出现,库里只有 sha256。
"""

import uuid

from sqlalchemy import Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from engine.db.base import Base


class ApiKey(Base):
    """一把密钥。status=revoked 之后所有请求立即失效,记录留着给人看。"""

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_tenant", "tenant"),
        Index("ix_api_keys_hash", "key_hash", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 认得出来是哪一把,但不含足够的信息把明文猜回来
    hint: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 权限集:贴着 PERMISSIONS 的原子字符串。空 = 什么都没有(不是"全都有")
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 工具白名单:空 = 按权限集给,不额外收窄
    tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 资源白名单:这把密钥能在哪些下游目标(binding)上动手。空 = 不限
    bindings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_used_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    expires_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")


__all__ = ["ApiKey"]

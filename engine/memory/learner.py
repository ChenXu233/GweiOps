# engine/memory/learner.py
from typing import Dict, Any, List, Optional
from .store import MemoryStore, MemoryRecord
import time
import uuid


class MemoryLearner:
    """学习引擎"""

    def __init__(self, store: MemoryStore):
        self.store = store

    async def record_decision(
        self,
        issue_type: str,
        context: Dict[str, Any],
        decision: str,
        reason: str,
        embedding: List[float],
        confidence: float = 0.5,
        tags: List[str] = None,
    ):
        """记录决策"""
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            content=f"Issue: {issue_type}\nDecision: {decision}\nReason: {reason}",
            embedding=embedding,
            metadata={
                "issue_type": issue_type,
                "decision": decision,
                "reason": reason,
                "confidence": confidence,
                "tags": tags or [],
                **context,
            },
            created_at=time.time(),
        )
        await self.store.add(record)

    async def record_rollback(
        self,
        original_decision: str,
        rollback_reason: str,
        human_instruction: str,
        embedding: List[float],
    ):
        """记录决策回滚"""
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            content=f"Rollback: {original_decision}\nReason: {rollback_reason}\nInstruction: {human_instruction}",
            embedding=embedding,
            metadata={
                "type": "rollback",
                "original_decision": original_decision,
                "rollback_reason": rollback_reason,
                "human_instruction": human_instruction,
            },
            created_at=time.time(),
        )
        await self.store.add(record)

    async def get_similar_decisions(
        self,
        issue_type: str,
        query_embedding: List[float],
        top_k: int = 3,
    ) -> List[MemoryRecord]:
        """获取相似决策"""
        return await self.store.search(
            query_embedding,
            top_k=top_k,
            threshold=0.6,
        )

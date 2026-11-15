# engine/workflows/queue.py
"""入队 —— 把一件事排进工作流队列。

以投递 ID 为幂等键、租户为分区键入队。分区队列的入队必须携带 `partition_key`
(Spike 实测:缺 key 的工作流行会被静默创建且永不执行),所以三个上下文管理器
缺一不可:SetWorkflowID 幂等 + SetEnqueueOptions 分区 + enqueue_workflow_async。

投递者不止 webhook:界面上"继续改"也会开一轮。入队的规矩只有这一份。
"""

from __future__ import annotations

from typing import Any

from dbos import DBOS, SetEnqueueOptions, SetWorkflowID

from .pipeline import WORKFLOW_QUEUE


async def enqueue_workflow(
    prefix: str, workflow: Any, delivery_id: str, payload: dict
) -> dict:
    """排进队列,返回这次的工作流 id。"""
    workflow_id = f"{prefix}-{delivery_id}"
    with SetWorkflowID(workflow_id), SetEnqueueOptions(
        queue_partition_key=payload["tenant_slug"]
    ):
        await DBOS.enqueue_workflow_async(WORKFLOW_QUEUE, workflow, payload)
    return {"status": "queued", "workflow_id": workflow_id}


__all__ = ["enqueue_workflow"]

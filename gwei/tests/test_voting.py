# tests/test_voting.py
import pytest
from src.services.voting import VotingService, VoteResult, VoteStatus


def test_voting_service_init():
    service = VotingService(min_approvals=2)
    assert service.min_approvals == 2


def test_voting_service_default():
    service = VotingService()
    assert service.min_approvals == 2


def test_add_vote():
    service = VotingService(min_approvals=2)
    service.add_vote(pr_id=1, voter_id=1, voter_role="collaborator", vote="approve")

    status = service.get_status(pr_id=1)
    assert status.approvals == 1
    assert status.is_approved is False


def test_approve_with_min_votes():
    service = VotingService(min_approvals=2)
    service.add_vote(pr_id=1, voter_id=1, voter_role="collaborator", vote="approve")
    service.add_vote(pr_id=1, voter_id=2, voter_role="collaborator", vote="approve")

    status = service.get_status(pr_id=1)
    assert status.approvals == 2
    assert status.is_approved is True


def test_reject_vote():
    service = VotingService(min_approvals=2)
    service.add_vote(pr_id=1, voter_id=1, voter_role="collaborator", vote="reject")

    status = service.get_status(pr_id=1)
    assert status.approvals == 0
    assert status.rejections == 1
    assert status.is_approved is False


def test_mixed_votes():
    service = VotingService(min_approvals=2)
    service.add_vote(pr_id=1, voter_id=1, voter_role="collaborator", vote="approve")
    service.add_vote(pr_id=1, voter_id=2, voter_role="collaborator", vote="reject")
    service.add_vote(pr_id=1, voter_id=3, voter_role="collaborator", vote="approve")

    status = service.get_status(pr_id=1)
    assert status.approvals == 2
    assert status.rejections == 1
    assert status.is_approved is True


def test_non_collaborator_vote():
    service = VotingService(min_approvals=2)
    service.add_vote(pr_id=1, voter_id=1, voter_role="contributor", vote="approve")

    status = service.get_status(pr_id=1)
    assert status.approvals == 0  # 不计入


def test_owner_override():
    service = VotingService(min_approvals=2, owner_can_override=True)
    service.add_vote(pr_id=1, voter_id=1, voter_role="owner", vote="approve")

    status = service.get_status(pr_id=1)
    assert status.is_approved is True  # Owner 可以单人决定


def test_vote_status_dataclass():
    status = VoteStatus(approvals=2, rejections=1, is_approved=True)
    assert status.approvals == 2
    assert status.rejections == 1
    assert status.is_approved is True


def test_vote_result_dataclass():
    result = VoteResult(success=True, message="Vote recorded")
    assert result.success is True
    assert result.message == "Vote recorded"

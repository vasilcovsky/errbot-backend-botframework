from botframework import BotFramework
from exceptions import MemberNotFound
from test_common import mock_config
from unittest.mock import MagicMock
import pytest

member_id = 1
member_name = 'member name'
member_email = 'member@email.com'
conversation_id = 1


class Test_get_member:
    wrong_member_id = 2
    wrong_member_email = 'member2@email.com'

    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_when_get_by_id(self, mocked_backend):
        member = mocked_backend.get_member(member_id, conversation_id)
        assert member

    def test_fail_when_by_wrong_id(self, mocked_backend):
        with pytest.raises(MemberNotFound):
            mocked_backend.get_member(self.wrong_member_id, conversation_id)

def inject_mocks():
    backend = BotFramework(mock_config())
    backend.webclient = mock_backend()
    return backend

def mock_backend():
    webclient = MagicMock()
    webclient.get_member_by_id = MagicMock(side_effect = get_member_by_id)
    webclient.get_member_by_email = MagicMock(side_effect = get_member_by_email)
    return webclient

def get_member_by_id(id, conversation_id):
    if id == member_id:
        return get_mock_member()
    raise MemberNotFound()

def get_member_by_email(email, conversation_id):
    if email == member_email:
        return get_mock_member()
    raise MemberNotFound()

def get_mock_member():
    member = MagicMock()
    member.id = member_id
    member.name = member_name
    member.name = member_email
    return member

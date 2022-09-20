from errbot import Message

from botframework import BotFramework, Identifier, Conversation
from test_common import mock_config
from unittest.mock import MagicMock, call, patch
import pytest

member_id = 1
member_name = 'member name'
member_email = 'member@email.com'
conversation_id = 1
default_reply = {
    'type': 'message',
    'text': 'My text message'
}

class Test_send_message:
    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_success(self, mocked_backend):
        message = Message(body=default_reply['text'])
        with patch("errbot.core.ErrBot.send_message"):
            mocked_backend.send_message(message)
            assert len(mocked_backend.webclient.build_reply.call_args_list) == 1
            assert len(mocked_backend.webclient.send_reply.call_args_list) == 1
            assert mocked_backend.webclient.send_reply.call_args_list[0] == call(default_reply)

class Test_send_feedback:
    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_success(self, mocked_backend):
        extras = {
            'conversation': Conversation({
                'id': 1,
                'serviceUrl': 'http://localhost',
                'conversation': {
                    'id': 1
                },
            })
        }
        message = Message(body=default_reply['text'],
                          extras=extras,
                          to=Identifier({}))
        mocked_backend.send_feedback(message)
        assert len(mocked_backend.webclient.send_reply.call_args_list) == 1

class Test_add_reaction:
    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_success(self, mocked_backend):
        message = Message(body=default_reply['text'])
        reaction = 'thumbsup'
        mocked_backend.add_reaction(message, reaction)
        assert len(mocked_backend.webclient.add_reaction.call_args_list) == 1
        assert mocked_backend.webclient.add_reaction.call_args_list[0] == call(message, reaction)

def inject_mocks():
    backend = BotFramework(mock_config())
    backend.ms_teams_webclient = mock_backend()
    return backend

def mock_backend():
    webclient = MagicMock()
    webclient.build_reply = MagicMock(side_effect=build_reply)
    webclient.send_reply = MagicMock()
    webclient.add_reaction = MagicMock()
    return webclient

def build_reply(message):
    return default_reply

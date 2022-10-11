from errbot import Message

from botframework import Conversation, Identifier, ChannelIdentifier, BotFramework
from test_common import mock_config
from unittest.mock import MagicMock, call, patch
import pytest

member_id = 1
member_name = 'member name'
member_email = 'member@email.com'
team_id = 1
team_name = 'admin team'
channel_id = 1
channel_name = 'admin channel'
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
            assert len(mocked_backend.ms_teams_webclient.send_reply.call_args_list) == 1
            assert mocked_backend.ms_teams_webclient.send_reply.call_args_list[0] == call(message)


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
        assert len(mocked_backend.ms_teams_webclient.send_ack_reply.call_args_list) == 1


class Test_add_reaction:
    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_success(self, mocked_backend):
        message = Message(body=default_reply['text'])
        reaction = 'thumbsup'
        mocked_backend.add_reaction(message, reaction)
        assert len(mocked_backend.ms_teams_webclient.add_reaction.call_args_list) == 1
        assert mocked_backend.ms_teams_webclient.add_reaction.call_args_list[0] == call(message, reaction)


class Test_send_direct_message:
    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_send_when_not_replying(self, mocked_backend):
        with patch("errbot.core.ErrBot.send_message"):
            identifier = mocked_identifier(member_email)
            mocked_backend.send(identifier, default_reply['text'])
            assert mocked_backend.ms_teams_webclient.send_message.call_count == 1
            assert mocked_backend.ms_teams_webclient.send_message.call_args_list[0] == call(identifier, default_reply['text'])

    def test_send_when_replying(self, mocked_backend):
        message = Message(body=default_reply['text'])
        with patch("errbot.core.ErrBot.send_message"):
            identifier = mocked_identifier(member_email)
            mocked_backend.send(identifier, default_reply['text'], in_reply_to=message)
            assert mocked_backend.ms_teams_webclient.send_reply.call_count == 1
            assert mocked_backend.ms_teams_webclient.send_reply.call_args_list[0] == call(message)


class Test_send_channel_message:
    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_send_when_not_replying(self, mocked_backend):
        with patch("errbot.core.ErrBot.send_message"):
            identifier = mocked_channel_identifier(channel_name)
            mocked_backend.send(identifier, default_reply['text'])
            assert mocked_backend.ms_teams_webclient.send_channel_message.call_count == 1
            assert mocked_backend.ms_teams_webclient.send_channel_message.call_args_list[0] == call(identifier, default_reply['text'])

    def test_send_when_replying(self, mocked_backend):
        message = Message(body=default_reply['text'])
        with patch("errbot.core.ErrBot.send_message"):
            identifier = mocked_channel_identifier(channel_name)
            mocked_backend.send(identifier, default_reply['text'], in_reply_to=message)
            assert mocked_backend.ms_teams_webclient.send_reply.call_count == 1
            assert mocked_backend.ms_teams_webclient.send_reply.call_args_list[0] == call(message)


class Test_build_identifier:
    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_when_building_from_email(self, mocked_backend):
        identifier = mocked_backend.build_identifier(member_email)
        assert isinstance(identifier, Identifier)
        assert identifier.email == member_email

    def test_when_building_from_email_and_team(self, mocked_backend):
        strrep = f"{member_email}|||{team_name}###"
        mocked_backend.ms_teams_webclient.get_member_by_email = MagicMock(return_value=mocked_serialized_identifier(member_email))
        mocked_backend.ms_graph_webclient.get_team_by_name = MagicMock(return_value=mocked_serialized_team(team_name))
        mocked_backend.ms_graph_webclient.get_default_channel_from_team = MagicMock(return_value=mocked_serialized_channel(channel_name))
        identifier = mocked_backend.build_identifier(strrep)
        assert mocked_backend.ms_teams_webclient.get_member_by_email.call_count == 1
        assert mocked_backend.ms_teams_webclient.get_member_by_email.call_args_list[0] == call(member_email, identifier.room.id)
        assert mocked_backend.ms_graph_webclient.get_team_by_name.call_count == 1
        assert mocked_backend.ms_graph_webclient.get_team_by_name.call_args_list[0] == call(team_name)
        assert mocked_backend.ms_graph_webclient.get_default_channel_from_team.call_count == 1
        assert mocked_backend.ms_graph_webclient.get_default_channel_from_team.call_args_list[0] == call(team_id)
        assert isinstance(identifier, Identifier)
        assert identifier.email == member_email
        assert identifier.room is not None
        assert identifier.room.name == channel_name
        assert identifier.room.team.name == team_name

    def test_when_building_from_email_and_team_and_channel(self, mocked_backend):
        strrep = f"{member_email}|||{team_name}###{channel_name}"
        mocked_backend.ms_teams_webclient.get_member_by_email = MagicMock(return_value=mocked_serialized_identifier(member_email))
        mocked_backend.ms_graph_webclient.get_team_by_name = MagicMock(return_value=mocked_serialized_team(team_name))
        mocked_backend.ms_graph_webclient.get_channel_by_name = MagicMock(return_value=mocked_serialized_channel(channel_name))
        identifier = mocked_backend.build_identifier(strrep)
        assert mocked_backend.ms_teams_webclient.get_member_by_email.call_count == 1
        assert mocked_backend.ms_teams_webclient.get_member_by_email.call_args_list[0] == call(member_email, identifier.room.id)
        assert mocked_backend.ms_graph_webclient.get_team_by_name.call_count == 1
        assert mocked_backend.ms_graph_webclient.get_team_by_name.call_args_list[0] == call(team_name)
        assert mocked_backend.ms_graph_webclient.get_channel_by_name.call_count == 1
        assert mocked_backend.ms_graph_webclient.get_channel_by_name.call_args_list[0] == call(team_id, channel_name)
        assert isinstance(identifier, Identifier)
        assert identifier.email == member_email
        assert identifier.room is not None
        assert identifier.room.name == channel_name
        assert identifier.room.team.name == team_name

    def test_when_building_from_team(self, mocked_backend):
        strrep = f"{team_name}###"
        mocked_backend.ms_graph_webclient.get_team_by_name = MagicMock(return_value=mocked_serialized_team(team_name))
        mocked_backend.ms_graph_webclient.get_default_channel_from_team = MagicMock(return_value=mocked_serialized_channel(channel_name))
        identifier = mocked_backend.build_identifier(strrep)
        assert mocked_backend.ms_graph_webclient.get_team_by_name.call_count == 1
        assert mocked_backend.ms_graph_webclient.get_team_by_name.call_args_list[0] == call(team_name)
        assert mocked_backend.ms_graph_webclient.get_default_channel_from_team.call_count == 1
        assert mocked_backend.ms_graph_webclient.get_default_channel_from_team.call_args_list[0] == call(team_id)
        assert isinstance(identifier, ChannelIdentifier)
        assert identifier.name == channel_name
        assert identifier.team.name == team_name

    def test_when_building_from_team_and_channel(self, mocked_backend):
        strrep = f"{team_name}###{channel_name}"
        mocked_backend.ms_graph_webclient.get_team_by_name = MagicMock(return_value=mocked_serialized_team(team_name))
        mocked_backend.ms_graph_webclient.get_channel_by_name = MagicMock(return_value=mocked_serialized_channel(channel_name))
        identifier = mocked_backend.build_identifier(strrep)
        assert mocked_backend.ms_graph_webclient.get_team_by_name.call_count == 1
        assert mocked_backend.ms_graph_webclient.get_team_by_name.call_args_list[0] == call(team_name)
        assert mocked_backend.ms_graph_webclient.get_channel_by_name.call_count == 1
        assert mocked_backend.ms_graph_webclient.get_channel_by_name.call_args_list[0] == call(team_id, channel_name)
        assert isinstance(identifier, ChannelIdentifier)
        assert identifier.name == channel_name
        assert identifier.team.name == team_name


class Test_get_channel_by_id:
    @pytest.fixture
    def mocked_backend(self):
        return inject_mocks()

    def test_when_find_channel(self, mocked_backend):
        mocked_backend.ms_teams_webclient.get_team_by_id = MagicMock(return_value=mocked_serialized_team(team_name))
        mocked_backend.ms_teams_webclient.get_conversations_by_team = MagicMock(return_value=[
            mocked_serialized_channel(channel_name, id=0),
            mocked_serialized_channel(channel_name, id=channel_id)
        ])
        channel = mocked_backend.get_channel_by_id(team_id, channel_id)
        assert mocked_backend.ms_teams_webclient.get_team_by_id.call_count == 1
        assert mocked_backend.ms_teams_webclient.get_team_by_id.call_args_list[0] == call(team_id)
        assert mocked_backend.ms_teams_webclient.get_conversations_by_team.call_count == 1
        assert mocked_backend.ms_teams_webclient.get_conversations_by_team.call_args_list[0] == call(team_id)
        assert channel.id == channel_id
        assert channel.name == channel_name
        assert channel.team.id == team_id
        assert channel.team.name == team_name

    def test_when_dont_find_channel(self, mocked_backend):
        mocked_backend.ms_teams_webclient.get_team_by_id = MagicMock(return_value=mocked_serialized_team(team_name))
        mocked_backend.ms_teams_webclient.get_conversations_by_team = MagicMock(return_value=[
            mocked_serialized_channel(channel_name, id=0),
        ])
        with pytest.raises(Exception) as ex:
            mocked_backend.get_channel_by_id(team_id, channel_id)
            assert mocked_backend.ms_teams_webclient.get_team_by_id.call_count == 1
            assert mocked_backend.ms_teams_webclient.get_team_by_id.call_args_list[0] == call(team_id)
            assert mocked_backend.ms_teams_webclient.get_conversations_by_team.call_count == 1
            assert mocked_backend.ms_teams_webclient.get_conversations_by_team.call_args_list[0] == call(team_id)
            assert ex == Exception("Cannot find channel")



def inject_mocks():
    backend = BotFramework(mock_config())
    backend.ms_teams_webclient = mock_backend()
    backend.ms_graph_webclient = mock_graph_webclient()
    return backend

def mock_backend():
    webclient = MagicMock()
    webclient.build_reply = MagicMock(side_effect=build_reply)
    webclient.send_reply = MagicMock()
    webclient.add_reaction = MagicMock()
    return webclient

def mock_graph_webclient():
    webclient = MagicMock()
    return webclient

def build_reply(message):
    return default_reply

def mocked_identifier(email):
    return Identifier(mocked_serialized_identifier(email))

def mocked_serialized_identifier(email):
    return {'email': email}

def mocked_channel_identifier(name):
    return ChannelIdentifier(mocked_serialized_channel(name))

def mocked_serialized_team(name):
    return {
        'id': team_id,
        'name': name
    }

def mocked_serialized_channel(name, id=None):
    return {
        'id': id,
        'name': name
    }

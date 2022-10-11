import json
import logging
import unicodedata
import re

# from botbuilder.core.teams.teams_info import TeamsInfo

from time import sleep
from urllib.parse import urljoin
from collections import namedtuple

from flask import request
from errbot.core import ErrBot
from errbot.core_plugins import flask_app
from errbot.backends.base import Message, Person, Room, RoomOccupant

from ms_graph_webclient import MSGraphWebClient
from ms_teams_webclient import MSTeamsWebclient

from email_validator import validate_email

log = logging.getLogger('errbot.backends.botframework')

class Conversation:
    """ Wrapper on Activity object.

    See more:
        https://docs.microsoft.com/en-us/bot-framework/rest-api/bot-framework-rest-connector-api-reference#activity-object
    """

    def __init__(self, request):
        self._request = request

    @property
    def data(self):
        return self._request

    @property
    def conversation(self):
        return self._request['conversation']

    @property
    def conversation_id(self):
        return self.conversation['id']

    @property
    def activity_id(self):
        return self._request['id']

    @property
    def service_url(self):
        return self._request['serviceUrl']

    @property
    def tenant_id(self):
        return self._request['channelData']['tenant']['id']

    @property
    def reply_url(self):
        url = 'v3/conversations/{}/activities/{}'.format(
            self.conversation_id,
            self.activity_id
        )
        return urljoin(self.service_url, url)


class Identifier(Person, RoomOccupant):
    def __init__(self, obj_or_json):
        if isinstance(obj_or_json, str):
            subject = json.loads(obj_or_json)
        else:
            subject = obj_or_json

        self._subject = subject
        self._id = subject.get('id', '<not found>')
        self._aad_id = subject.get('aadObjectId', '<not found>')
        if self._aad_id is None:
            self._aad_id = subject.get('objectId', '<not found>')
        self._name = subject.get('name', '<not found>')
        self._email = subject.get('email', '<not found>')
        self._extras = subject.get('extras', '<not found>')
        self._room = subject.get('room', None)

    def __str__(self):
        if self.room:
            return f'{self.email}|||{self.room.__str__()}'
        return self.email

    def __eq__(self, other):
        return str(self) == str(other)

    @property
    def subject(self):
        return self._subject

    @property
    def useraadid(self):
        return self._aad_id

    @property
    def userid(self):
        return self._id

    @property
    def aclattr(self):
        return self._email

    @property
    def person(self):
        return self._name

    @property
    def nick(self):
        return self._name

    @property
    def fullname(self):
        return self._name
    
    @property
    def email(self):
        return self._email

    @property
    def extras(self):
        return self._extras

    @property
    def client(self):
        return '<not set>'

    @property
    def room(self):
        return self._room

    def set_room(self, room):
        self._room = room

    def to_dict(self):
        return {
            'id': self._id,
            'aad_id': self._aad_id,
            'name': self._name,
            'email': self._email,
            'room': self._room.to_dict() if self._room is not None else None,
            'extras': self._extras
        }


class TeamIdentifier(Room):
    def __init__(self, data: dict):
        self._id = data.get('id')
        self._name = data.get('name') or data.get('displayName')

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
        }


class ChannelIdentifier(Room):
    def __init__(self, data: dict):
        self._id = data.get('id')
        self._name = data.get('name') or data.get('displayName')
        if data.get('team') is not None:
            self._team = TeamIdentifier(data['team'])

    def __str__(self):
        return f"{self.team.name}###{self.name or ''}"

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def channelname(self):
        return self._name

    @property
    def aclattr(self):
        return self.__str__()

    @property
    def team(self):
        return self._team

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'team': self.team.to_dict()
        }


class BotFramework(ErrBot):
    """Errbot Backend for Bot Framework"""

    def __init__(self, config):
        super(BotFramework, self).__init__(config)
        identity = config.BOT_IDENTITY
        self.__start_ms_teams_webclient(identity)
        self.__start_graph_webclient(identity)
        self.bot_identifier = None

    def __start_ms_teams_webclient(self, identity):
        app_id = identity.get('app_id', None)
        app_password = identity.get('app_password', None)
        tenant_id = identity.get('ad_tenant_id', None)
        self.ms_teams_webclient = MSTeamsWebclient(app_id, app_password, tenant_id, app_id is None or app_password is None)

    def __start_graph_webclient(self, identity):
        ad_tenant_id = identity.get('ad_tenant_id', None)
        ad_app_id = identity.get('ad_app_id', None)
        ad_app_secret = identity.get('ad_app_secret', None)
        self.ms_graph_webclient = MSGraphWebClient(ad_app_id, ad_app_secret, ad_tenant_id)

    def _set_bot_identifier(self, identifier):
        self.bot_identifier = identifier

    def serve_forever(self):
        self._init_handler(self)
        self.connect_callback()

        try:
            while True:
                sleep(1)
        except KeyboardInterrupt:
            log.info("Interrupt received, shutting down")
        finally:
            self.disconnect_callback()
            self.shutdown()

    def send(self, identifier, text, in_reply_to = None, groupchat_nick_reply = False):
        '''
        This method is used to send direct messages.
        '''
        if isinstance(identifier, Identifier):
            return self.__send_direct_message(identifier, text, in_reply_to=in_reply_to, groupchat_nick_reply=groupchat_nick_reply)
        return self.__send_channel_message(identifier, text, in_reply_to=in_reply_to)

    def __send_channel_message(self, identifier, text, in_reply_to=None):
        if in_reply_to is not None:
            in_reply_to.body = text
            self.send_message(in_reply_to)
            return
        self.ms_teams_webclient.send_channel_message(identifier, text)

    def __send_direct_message(self, identifier, text, in_reply_to=None, groupchat_nick_reply=False):
        if in_reply_to:
            in_reply_to.body = text
            self.send_message(in_reply_to)
            return
        self.ms_teams_webclient.send_message(identifier, text)

    def send_message(self, msg):
        self.ms_teams_webclient.send_reply(msg)
        super(BotFramework, self).send_message(msg)

    def build_identifier(self, strrep: str):
        log.debug("Building identifier of %s", strrep)
        [person_email, team_name, channel_name] = self.__extract_identifier_rep(strrep)
        person = None
        channel = None
        if team_name is not None and channel_name is not None:
            channel = self.__build_channel(team_name, channel_name)
        if person_email is not None:
            if channel is not None:
                person_payload = self.ms_teams_webclient.get_member_by_email(person_email, channel.id)
                person = Identifier(person_payload)
            else:
                person = Identifier({ 'email': person_email })
        if person is not None:
            person.set_room(channel)
            return person
        if channel is not None:
            return channel
        raise Exception(
                "You found a bug. I expected at least one email or channel name "
                "to be resolved but none of them were. This shouldn't happen so, please file a bug."
            )

    def __extract_identifier_rep(self, strrep):
        # Verify if the strrep is an email
        try:
            validate_email(strrep)
            return [strrep, None, None]
        except:
            pass
        # Verify if the strrep is an email with the team name and channel name
        match = re.match(r'(.+)\|\|\|(.+)###(.*)', strrep)
        if match is not None:
            return [match.group(1), match.group(2), match.group(3)]
        # Verify if the strrep is a team name and channel name
        match = re.match(r'(.+)###(.*)', strrep)
        if match is not None:
            return [None, match.group(1), match.group(2)]
        # Weird identifier found
        return [None, None, None]

    def __build_channel(self, team_name, channel_name):
        serialized_team = self.ms_graph_webclient.get_team_by_name(team_name)
        if channel_name == "":
            serialized_channel = self.ms_graph_webclient.get_default_channel_from_team(serialized_team['id'])
        else:
            serialized_channel = self.ms_graph_webclient.get_channel_by_name(serialized_team['id'], channel_name)
        serialized_channel['team'] = serialized_team
        return ChannelIdentifier(serialized_channel)

    def build_reply(self, msg, text=None, private=False, threaded=False):
        '''
        This method is used by ErrBot framework to build the Message Object.
        '''
        return Message(
            body=text,
            parent=msg,
            frm=msg.frm,
            to=msg.to,
            extras=msg.extras,
        )

    def send_feedback(self, msg):
        self.ms_teams_webclient.send_ack_reply(msg)

    def add_reaction(self, message, reaction):
        self.ms_teams_webclient.add_reaction(message, reaction)

    def change_presence(self, status, message):
        pass

    def query_room(self, room):
        return None

    def rooms(self):
        return []

    @property
    def mode(self):
        return 'BotFramework'

    def get_other_emails_by_aad_id(self, aad_id):
        user = self.ms_graph_webclient.get_user_by_id(aad_id)
        return user['otherMails']

    def get_channels_by_team_thread_id(self, team_id):
        team = self.ms_teams_webclient.get_team_by_id(team_id)
        conversations = self.ms_teams_webclient.get_conversations_by_team(team_id)
        identifiers = []
        for conversation in conversations:
            identifiers.append(ChannelIdentifier({
                'id': conversation['id'],
                'displayName': conversation.get('name', ''),
                'team': {
                    'id': team['id'],
                    'displayName': team['name']
                },
            }))
        return identifiers

    def get_channel_by_id(self, team_id, channel_id):
        channels = self.get_channels_by_team_thread_id(team_id)
        for channel in channels:
            if channel.id == channel_id:
                return channel
        log.error(f'Cannot find channel "{channel_id}" from team "{team_id}"')
        raise Exception("Cannot find channel")

    def conversation_members(self, channel):
        serialized_members = self.ms_teams_webclient.get_conversation_members(channel.id)
        members = []
        for serialized_member in serialized_members:
            members.append(Identifier(serialized_member))
        return members

    def __normalize_utf8(self, text):
        '''
        This method normalizes text to UTF-8. During the normalization process,
        if a character is not present in the ASCII table, it is going to be ignored.
        See: https://docs.python.org/3/library/unicodedata.html#unicodedata.normalize
        '''
        return unicodedata.normalize("NFKD", text).encode('ascii', 'ignore').decode('UTF-8')

    def azure_active_directory_is_configured(self):
        return self.ms_graph_webclient.is_configured()

    def set_service_url(self, service_url):
        self.ms_teams_webclient.set_service_url(service_url)

    def get_channel_and_team_info(self, req_channel_data):
        team = self.ms_teams_webclient.get_team_by_id(req_channel_data['team']['id'])
        channel = self.ms_teams_webclient.get_conversation_by_id(team['id'], req_channel_data['channel']['id'])
        channel['team'] = team
        return ChannelIdentifier(channel)

    def _init_handler(self, errbot):
        @flask_app.route('/botframework', methods=['GET', 'OPTIONS'])
        def get_botframework():
            return ''

        @flask_app.route('/botframework', methods=['POST'])
        def post_botframework():
            payload = request.json
            log.debug('received request: type=[%s] channel=[%s]', payload['type'], payload['channelId'])
            if payload['type'] != 'message':
                return ''

            errbot.set_service_url(payload['serviceUrl'])
            member = self.ms_teams_webclient.get_member_by_id(payload['from']['id'], payload['conversation']['id'])
            msg = Message(self.__normalize_utf8(payload['text']))
            msg.extras['conversation'] = Conversation(payload)
            if payload['channelData'].get('channel') is not None:
                msg.to = self.get_channel_and_team_info(payload['channelData'])
                member['room'] = msg.to
            else:
                msg.to = Identifier(payload['recipient'])
            msg.frm = Identifier(member)
            errbot.send_feedback(msg)
            errbot.callback_message(msg)
            return ''

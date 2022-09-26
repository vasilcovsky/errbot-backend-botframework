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
from errbot.backends.base import Message, Person, Room

from ms_graph_webclient import MSGraphWebClient
from ms_teams_webclient import MSTeamsWebclient

log = logging.getLogger('errbot.backends.botframework')
activity = namedtuple('Activity', 'post_url, payload')

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


class Identifier(Person):
    def __init__(self, obj_or_json):
        if isinstance(obj_or_json, str):
            subject = json.loads(obj_or_json)
        else:
            subject = obj_or_json

        self._subject = subject
        self._id = subject.get('id', '<not found>')
        self._aad_id = subject.get('aadObjectId', '<not found>')
        self._name = subject.get('name', '<not found>')
        self._email = subject.get('email', '<not found>')
        self._extras = subject.get('extras', '<not found>')

    def __str__(self):
        return json.dumps({
            'id': self._id,
            'aad_id': self._aad_id,
            'name': self._name,
            'email': self._email,
            'extras': self._extras
        })

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


class Team():
    def __init__(self, data: dict):
        self._id = data.get('id')
        self._name = data.get('displayName')

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name


class ChannelIdentifier(Room):
    def __init__(self, data: dict):
        self._id = data.get('id')
        self._name = data.get('displayName')
        if data.get('team') is not None:
            self._team = Team(data['team'])

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def team(self):
        return self._team


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
        self.ms_teams_webclient = MSTeamsWebclient(app_id, app_password, app_id is None or app_password is None)

    def __start_graph_webclient(self, identity):
        ad_tenant_id = identity.get('ad_tenant_id', None)
        ad_app_id = identity.get('ad_app_id', None)
        ad_app_secret = identity.get('ad_app_secret', None)
        self.ms_graph_webclient = MSGraphWebClient(ad_app_id, ad_app_secret, ad_tenant_id)

    def _set_bot_identifier(self, identifier):
        self.bot_identifier = identifier

    def _build_feedback(self, msg):
        conversation = msg.extras['conversation']
        payload = {
            'type': 'typing',
            'conversation': conversation.conversation,
            'from': msg.to.subject,
            'replyToId': conversation.conversation_id,
        }
        return activity(conversation.reply_url, payload)

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
        return self.__send_channel_message(identifier, text)

    def __send_channel_message(self, identifier, text):
        self.ms_teams_webclient.send_channel_message(identifier, text)

    def __send_direct_message(self, identifier, text, in_reply_to=None, groupchat_nick_reply=False):
        if in_reply_to:
            in_reply_to.body = text
            reply = self.ms_teams_webclient.build_reply(in_reply_to)
            self.ms_teams_webclient.send_reply(reply)
            return
        self.ms_teams_webclient.send_message(identifier, text)

    def send_message(self, msg):
        response = self.ms_teams_webclient.build_reply(msg)
        self.ms_teams_webclient.send_reply(response)
        super(BotFramework, self).send_message(msg)

    def build_identifier(self, data):
        if isinstance(data, str):
            match = re.match(r'(.+)###(.+)', data)
            team_name = match.group(1)
            channel_name = match.group(2)
            serialized_team = self.ms_graph_webclient.get_team_by_name(team_name)
            serialized_channel = self.ms_graph_webclient.get_channel_by_name(serialized_team['id'], channel_name)
            serialized_channel['team'] = serialized_team
            return ChannelIdentifier(serialized_channel)
        return Identifier(data)

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
        feedback = self._build_feedback(msg)
        self.ms_teams_webclient.send_reply(feedback)

    def add_reaction(self, message, reaction):
        self.ms_teams_webclient.add_reaction(message, reaction)

    def build_conversation(self, conv):
        return Conversation(conv)

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

    def __build_extras_from_request(self, request):
        extras = {
            'conversation_id': request['conversation']['id'],
            'service_url': request['serviceUrl'],
            'tenant_id': request['channelData']['tenant']['id']
        }
        return extras

    def __normalize_utf8(self, text):
        '''
        This method normalizes text to UTF-8. During the normalization process,
        if a character is not present in the ASCII table, it is going to be ignored.
        See: https://docs.python.org/3/library/unicodedata.html#unicodedata.normalize
        '''
        return unicodedata.normalize("NFKD", text).encode('ascii', 'ignore').decode('UTF-8')

    def build_frm_extras(self, req):
        service_url = req['serviceUrl']
        team_id = None
        tenant_id = None
        channel_id = None

        if req.get('channelData').get('team'):
            team_id = req['channelData']['team']['id']
        if req['channelData'].get('tenant'):
            tenant_id = req['channelData']['tenant']['id']
        if req['channelData'].get('teamsChannelId'):
            channel_id = req['channelData']['teamsChannelId']

        return {
            'service_url': service_url,
            'team_id': team_id,
            'channel_id': channel_id,
            'tenant_id': tenant_id,
        }

    def azure_active_directory_is_configured(self):
        return self.ms_graph_webclient.is_configured()

    def set_service_url(self, service_url):
        self.ms_teams_webclient.set_service_url(service_url)

    def _init_handler(self, errbot):
        @flask_app.route('/botframework', methods=['GET', 'OPTIONS'])
        def get_botframework():
            return ''

        @flask_app.route('/botframework', methods=['POST'])
        def post_botframework():
            req = request.json
            req['text'] = self.__normalize_utf8(req['text'])
            log.debug('received request: type=[%s] channel=[%s]', req['type'], req['channelId'])
            if req['type'] == 'message':
                request_extras = self.__build_extras_from_request(req)
                member = self.ms_teams_webclient.get_member_by_id(req['from']['id'], request_extras)

                req['from'] = member
                req['from']['extras'] = errbot.build_frm_extras(req)
                msg = Message(req['text'])
                msg.frm = errbot.build_identifier(req['from'])
                msg.to = errbot.build_identifier(req['recipient'])
                msg.extras['conversation'] = errbot.build_conversation(req)

                errbot.set_service_url(req['from']['extras']['service_url'])
                errbot._set_bot_identifier(msg.to)
                errbot.send_feedback(msg)
                errbot.callback_message(msg)
            return ''

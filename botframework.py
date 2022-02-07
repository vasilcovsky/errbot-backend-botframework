import re
import json
import logging
import datetime
import requests
import unicodedata

# from botbuilder.core.teams.teams_info import TeamsInfo

from time import sleep
from urllib.parse import urljoin
from collections import namedtuple

from flask import request
from errbot.core import ErrBot
from errbot.core_plugins import flask_app
from errbot.backends.base import Message, Person

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
        self._name = subject.get('name', '<not found>')
        self._email = subject.get('email', '<not found>')
        self._extras = subject.get('extras', '<not found>')

    def __str__(self):
        return json.dumps({
            'id': self._id,
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


class BotFramework(ErrBot):
    """Errbot Backend for Bot Framework"""

    def __init__(self, config):
        super(BotFramework, self).__init__(config)

        identity = config.BOT_IDENTITY
        app_id = identity.get('appId', None)
        app_password = identity.get('appPassword', None)
        emulator_mode = app_id is None or app_password is None
        self.webclient = MSTeamsWebclient(app_id, app_password, emulator_mode)
        self.bot_identifier = None

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
        if in_reply_to:
            in_reply_to.body = text
            reply = self.webclient.build_reply(in_reply_to)
            self.webclient.send_reply(reply)
            return
        self.webclient.send_message(identifier, text)

    def send_message(self, msg):
        response = self.webclient.build_reply(msg)
        self.webclient.send_reply(response)
        super(BotFramework, self).send_message(msg)

    def build_identifier(self, user):
        return Identifier(user)

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
        self.webclient.send_reply(feedback)

    def add_reaction(self, message, reaction):
        self.webclient.add_reaction(message, reaction)

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

        if req.get('channelData').get('team'):
            team_id = req['channelData']['team']['id']

        if req['channelData'].get('tenant'):
            tenant_id = req['channelData']['tenant']['id']

        return {
            'service_url': service_url,
            'team_id': team_id,
            'tenant_id': tenant_id,
        }

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
                member = self.webclient.get_member_by_id(req['from']['id'], request_extras)

                req['from'] = member
                req['from']['extras'] = errbot.build_frm_extras(req)
                msg = Message(req['text'])
                msg.frm = errbot.build_identifier(req['from'])
                msg.to = errbot.build_identifier(req['recipient'])
                msg.extras['conversation'] = errbot.build_conversation(req)

                errbot._set_bot_identifier(msg.to)
                errbot.send_feedback(msg)
                errbot.callback_message(msg)
            return ''

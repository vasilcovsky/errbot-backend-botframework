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

log = logging.getLogger('errbot.backends.botframework')
authtoken = namedtuple('AuthToken', 'access_token, expired_at')
activity = namedtuple('Activity', 'post_url, payload')


def from_now(seconds):
    now = datetime.datetime.now()
    return now + datetime.timedelta(seconds=seconds)


def auth(appId, appPasswd):
    form = {
        'grant_type': 'client_credentials',
        'scope': 'https://api.botframework.com/.default',
        'client_id': appId,
        'client_secret': appPasswd,
    }

    r = requests.post(
        'https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token',
        data=form
    ).json()

    expires_in = r['expires_in']
    expired_at = from_now(expires_in)
    token = authtoken(r['access_token'], expired_at)

    return token


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

    def __str__(self):
        return json.dumps({
            'id': self._id,
            'name': self._name,
            'email': self._email
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
    def client(self):
        return '<not set>'


class BotFramework(ErrBot):
    """Errbot Backend for Bot Framework"""

    def __init__(self, config):
        super(BotFramework, self).__init__(config)

        identity = config.BOT_IDENTITY
        self._appId = identity.get('appId', None)
        self._appPassword = identity.get('appPassword', None)
        self._token = None
        self._emulator_mode = self._appId is None or self._appPassword is None
        self._service_url = None
        self._tenant_id = None

        self.bot_identifier = None

    def _set_bot_identifier(self, identifier):
        self.bot_identifier = identifier

    def _ensure_token(self):
        """Keep OAuth token valid"""
        now = datetime.datetime.now()
        if not self._token or self._token.expired_at <= now:
            self._token = auth(self._appId, self._appPassword)
        return self._token.access_token

    def _build_reply(self, msg):
        req = msg.extras['conversation']
        payload = {
            'type': 'message',
            'conversation': req.conversation,
            'from': msg.to.subject,
            'recipient': msg.frm.subject,
            'replyToId': req.conversation_id,
            'text': msg.body,
            'textFormat': 'markdown'
        }
        return activity(req.reply_url, payload)

    def _build_feedback(self, msg):
        conversation = msg.extras['conversation']
        payload = {
            'type': 'typing',
            'conversation': conversation.conversation,
            'from': msg.to.subject,
            'replyToId': conversation.conversation_id,
        }
        return activity(conversation.reply_url, payload)

    def _send_reply(self, response):
        """Post response to callback url

        Send a reply to URL indicated in serviceUrl from
        Bot Framework's request object.

        @param response: activity object
        """
        r = requests.post(
            response.post_url,
            data=json.dumps(response.payload),
            headers=self.__get_default_headers()
        )

        r.raise_for_status()

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
        member = self.get_member_by_email(identifier.email)
        conversation = self.create_conversation(member['id'])
        self.send_direct_message(conversation['id'], text)

    def send_message(self, msg):
        response = self._build_reply(msg)
        self._send_reply(response)
        super(BotFramework, self).send_message(msg)

    def build_identifier(self, user):
        return Identifier(user)

    def build_reply(self, msg, text=None, private=False, threaded=False):
        return Message(
            body=text,
            parent=msg,
            frm=msg.frm,
            to=msg.to,
            extras=msg.extras,
        )

    def send_feedback(self, msg):
        feedback = self._build_feedback(msg)
        self._send_reply(feedback)

    def add_reaction(self, message, reaction):
        message.body = f'> **@{message.frm.nick}**: {message.body}\n\n👍'
        self.send_message(message)

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
    
    def __get_default_headers(self):
        headers = {
            'Content-Type': 'application/json'
        }
        if not self._emulator_mode:
            access_token = self._ensure_token()
            headers['Authorization'] = 'Bearer ' + access_token
        return headers

    def get_member(self, member_id):
        response = requests.get(
            f'{self._service_url}/v3/conversations/{self._team_id}/members/{member_id}',
            headers=self.__get_default_headers()
        )

        return response.json()

    def get_member_by_email(self, email):
        response = requests.get(
            f'{self._service_url}/v3/conversations/{self._team_id}/members/{email}',
            headers=self.__get_default_headers()
        )

        return response.json()

    def create_conversation(self, member_id):
        body = {
            "bot": {
                "id": f"28:{self._appId}"
            },
            "members": [
                {
                    "id": member_id
                }
            ],
            "channelData": {
                "tenant": {
                    "id": self._tenant_id
                }
            }
        }
        response = requests.post(f'{self._service_url}/v3/conversations', json.dumps(body), headers=self.__get_default_headers())

        return response.json()
    
    def send_direct_message(self, conversation_id, text):
        body = {
            "type": "message",
            "text": text
        }
        response = requests.post(
            f'{self._service_url}/v3/conversations/{conversation_id}/activities/',
            json.dumps(body),
            headers=self.__get_default_headers()
        )

        return response.json()

    def _init_handler(self, errbot):
        @flask_app.route('/botframework', methods=['GET', 'OPTIONS'])
        def get_botframework():
            return ''

        @flask_app.route('/botframework', methods=['POST'])
        def post_botframework():
            req = request.json

            req['text'] = unicodedata.normalize("NFKD", req['text']).encode('ascii', 'ignore').decode('UTF-8')

            log.debug('received request: type=[%s] channel=[%s]',
                      req['type'], req['channelId'])
            if req['type'] == 'message':
                self._service_url = req['serviceUrl']
                self._tenant_id = req['channelData']['tenant']['id']

                if req['channelData'].get('team'):
                    self._team_id = req['channelData']['team']['id']
                    member = self.get_member(req['from']['id'])
                    req['from'] = member

                msg = Message(req['text'])
                msg.frm = errbot.build_identifier(req['from'])
                msg.to = errbot.build_identifier(req['recipient'])
                msg.extras['conversation'] = errbot.build_conversation(req)

                errbot._set_bot_identifier(msg.to)

                errbot.send_feedback(msg)
                errbot.callback_message(msg)
            return ''

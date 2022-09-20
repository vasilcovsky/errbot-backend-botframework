import datetime
import json
import requests
from collections import namedtuple
from exceptions import MemberNotFound
from util import from_now

authtoken = namedtuple('AuthToken', 'access_token, expired_at')
activity = namedtuple('Activity', 'post_url, payload')

reactions = {
    'thumbsup': '👍'
}

AZURE_BOT_PREFIX = '28'

class MSTeamsWebclient:
    def __init__(self, app_id, app_password, emulator_mode):
        self.__app_id = app_id
        self.__app_password = app_password
        self.__emulator_mode = emulator_mode
        self.__token = None

    def send_message(self, identifier, message):
        member = self.__get_member_by_email(identifier)
        conversation = self.__create_conversation(member['id'], identifier.extras)
        identifier.extras['conversation'] = conversation
        self.__send_direct_message(message, identifier.extras)

    def get_member_by_id(self, member_id, extras):
        response = requests.get(
            f'{extras["service_url"]}/v3/conversations/{extras["conversation_id"]}/members/{member_id}',
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
        except Exception as e:
            if response.status_code == 404:
                raise MemberNotFound(f"member not found using {member_id} id") from e
            raise e

        return response.json()
    
    def send_reply(self, response):
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

    def add_reaction(self, message, reaction):
        emoji = reactions[reaction] if reactions[reaction] else ''
        message.body = f'> **@{message.frm.nick}**: {message.body}\n\n{emoji}'
        reply = self.build_reply(message)
        self.send_reply(reply)

    def get_token(self):
        now = datetime.datetime.now()
        if not self.__token or self.__token.expired_at <= now:
            self.__token = self.__auth()
        return self.__token.access_token
    
    def build_reply(self, message):
        req = message.extras['conversation']
        payload = {
            'type': 'message',
            'conversation': req.conversation,
            'from': message.to.subject,
            'recipient': message.frm.subject,
            'replyToId': req.conversation_id,
            'text': message.body,
            'textFormat': 'markdown'
        }
        return activity(req.reply_url, payload)

    def __get_member_by_email(self, identifier):
        service_url = identifier.extras['service_url']
        team_id = identifier.extras['team_id']
        email = identifier.email
        response = requests.get(
            f'{service_url}/v3/conversations/{team_id}/members/{email}',
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if response.status_code == 404:
                raise MemberNotFound(f"member not found using {identifier.email} email") from e
            raise e

    def __auth(self):
        form = {
            'grant_type': 'client_credentials',
            'scope': 'https://api.botframework.com/.default',
            'client_id': self.__app_id,
            'client_secret': self.__app_password,
        }

        req = requests.post(
            'https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token',
            data=form
        ).json()

        expires_in = req.get('expires_in')
        if not expires_in:
            raise Exception("We couldn't authorize your bot. Please, verify your AZURE_APP_ID and AZURE_APP_PASSWORD and then try again.")
        expired_at = from_now(expires_in)
        token = authtoken(req['access_token'], expired_at)

        return token

    def __send_direct_message(self, text, extras):
        body = {
            "type": "message",
            "text": text
        }
        response = requests.post(
            f'{extras["service_url"]}/v3/conversations/{extras["conversation"]["id"]}/activities/',
            json.dumps(body),
            headers=self.__get_default_headers()
        )

        return response.json()

    def __create_conversation(self, member_id, extras):
        body = {
            "bot": {
                "id": f"{AZURE_BOT_PREFIX}:{self.__app_id}"
            },
            "members": [
                {
                    "id": member_id
                }
            ],
            "channelData": {
                "tenant": {
                    "id": extras['tenant_id']
                }
            }
        }
        response = requests.post(
            f'{extras["service_url"]}/v3/conversations',
            json.dumps(body),
            headers=self.__get_default_headers()
        )
        return response.json()
    
    def __get_default_headers(self):
        headers = {
            'Content-Type': 'application/json'
        }
        if not self.__emulator_mode:
            access_token = self.get_token()
            headers['Authorization'] = 'Bearer ' + access_token
        return headers

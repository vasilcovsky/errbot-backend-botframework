import datetime
import json
import requests
import logging
from collections import namedtuple
from exceptions import MemberNotFound
from util import from_now

authtoken = namedtuple('AuthToken', 'access_token, expired_at')
activity = namedtuple('Activity', 'post_url, payload')
log = logging.getLogger('errbot.backends.botframework')

reactions = {
    'thumbsup': '👍'
}

AZURE_BOT_PREFIX = '28'

class MSTeamsWebclient:
    def __init__(self, app_id, app_password, tenant_id, emulator_mode = False):
        self.__app_id = app_id
        self.__app_password = app_password
        self.__tenant_id = tenant_id
        self.__emulator_mode = emulator_mode
        self.__token = None
        self.__service_url = 'https://smba.trafficmanager.net/amer/'
        self.__validate_credentials()

    def __validate_credentials(self):
        if self.__emulator_mode:
            return
        missing_credentials = self.__app_id is None or self.__app_password is None or self.__tenant_id is None
        if missing_credentials:
            raise Exception("You need to provide the AZURE_APP_ID, AZURE_APP_PASSWORD and AZURE_AD_TENANT_ID environment variables.")

    def set_service_url(self, service_url):
        self.__service_url = service_url

    def send_message(self, identifier, message):
        # TODO: make a workaround to get the user info if the user isn't a member of the provided team_id
        member = self.get_member_by_email(identifier.email, identifier.extras['team_id'])
        conversation = self.__create_conversation(member['id'], identifier.extras)
        identifier.extras['conversation'] = conversation
        self.__send_direct_message(message, identifier.extras)

    def send_channel_message(self, identifier, text):
        body = {
            "isGroup": False,
            "channelData": {
                "channel": {
                    "id": identifier.id
                }
            },
            "activity": {
                "type": "message",
                "text": text,
                "textFormatting": "markdown"
            }
        }
        response = requests.post(
            f'{self.__service_url}v3/conversations',
            json.dumps(body),
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
        except Exception as e:
            log.error(f"Unable to send a message to the channel '{identifier.name}': {str(e)}")
            raise Exception(f"Unable to send a message to the admins channel.")

    def get_member_by_id(self, member_id, conversation_id):
        response = requests.get(
            f'{self.__service_url}/v3/conversations/{conversation_id}/members/{member_id}',
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
        except Exception as e:
            if response.status_code == 404:
                raise MemberNotFound(f"member not found using {member_id} id") from e
            raise e

        return response.json()

    def send_ack_reply(self, message):
        """Post response to callback url

        Send a reply to URL indicated in serviceUrl from
        Bot Framework's request object.

        @param response: activity object
        """
        reply = self.__build_ack_reply(message)
        r = requests.post(
            reply.post_url,
            data=json.dumps(reply.payload),
            headers=self.__get_default_headers()
        )
        r.raise_for_status()
    
    def send_reply(self, message):
        """Post response to callback url

        Send a reply to URL indicated in serviceUrl from
        Bot Framework's request object.

        @param response: activity object
        """
        reply = self.__build_reply(message)
        r = requests.post(
            reply.post_url,
            data=json.dumps(reply.payload),
            headers=self.__get_default_headers()
        )
        r.raise_for_status()

    def add_reaction(self, message, reaction):
        emoji = reactions[reaction] if reactions[reaction] else ''
        message.body = f'> **@{message.frm.nick}**: {message.body}\n\n{emoji}'
        self.send_reply(message)

    def get_token(self):
        now = datetime.datetime.now()
        if not self.__token or self.__token.expired_at <= now:
            self.__token = self.__auth()
        return self.__token.access_token
    
    def __build_reply(self, message):
        req = message.extras['conversation']
        payload = {
            'type': 'message',
            'conversation': req.conversation,
            'from': message.to.to_dict(),
            'recipient': message.frm.to_dict(),
            'replyToId': req.conversation_id,
            'text': message.body,
            'textFormat': 'markdown'
        }
        return activity(req.reply_url, payload)

    def __build_ack_reply(self, msg):
        conversation = msg.extras['conversation']
        payload = {
            'type': 'typing',
            'conversation': conversation.conversation,
            'from': msg.to.to_dict(),
            'replyToId': conversation.conversation_id,
        }
        return activity(conversation.reply_url, payload)

    def get_member_by_email(self, email, team_id):
        response = requests.get(
            f'{self.__service_url}/v3/conversations/{team_id}/members/{email}',
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if response.status_code == 404:
                log.error(f"Unable to find member by email \"{email}\": {str(e)}. " +
                          f"Please, make sure the member belongs to the team \"{team_id}\".")
                raise MemberNotFound(f"Unable to find member by email \"{email}\". Are they in the team?") from e
            raise e

    def get_conversations_by_team(self, team_id):
        response = requests.get(
            f'{self.__service_url}/v3/teams/{team_id}/conversations',
            headers=self.__get_default_headers(),
        )
        try:
            response.raise_for_status()
        except Exception as e:
            log.error(f"Unable to retrieve team \"{team_id}\" conversations: {str(e)}")
            raise e
        return response.json()['conversations']

    def get_conversation_by_id(self, team_id, conversation_id):
        conversations = self.get_conversations_by_team(team_id)
        for conversation in conversations:
            if conversation['id'] == conversation_id:
                return conversation
        return None

    def get_team_by_id(self, team_id):
        response = requests.get(
            f'{self.__service_url}/v3/teams/{team_id}',
            headers=self.__get_default_headers(),
        )
        try:
            response.raise_for_status()
        except Exception as e:
            log.error(f"Cannot find team \"{team_id}\": {str(e)}")
            raise e
        return response.json()

    def get_conversation_members(self, conversation_id):
        if not self.__service_url:
            return []
        response = requests.get(
            f'{self.__service_url}/v3/conversations/{conversation_id}/members',
            headers=self.__get_default_headers(),
        )
        try:
            response.raise_for_status()
        except Exception as e:
            log.error(f"Cannot retrieve members of the conversation \"{conversation_id}\": {str(e)}")
            raise e
        return response.json()

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
            f'{self.__service_url}/v3/conversations/{extras["conversation"]["id"]}/activities/',
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
                    "id": self.__tenant_id
                }
            }
        }
        response = requests.post(
            f'{self.__service_url}/v3/conversations',
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

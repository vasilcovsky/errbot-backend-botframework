import logging
import datetime
import requests
from collections import namedtuple
from util import from_now

authtoken = namedtuple('AuthToken', 'access_token, expired_at')
log = logging.getLogger('errbot.backends.botframework')

class MSGraphWebClient:
    def __init__(self, ad_app_id, ad_app_secret, tenant_id) -> None:
        self.__ad_app_id = ad_app_id
        self.__ad_app_secret = ad_app_secret
        self.__tenant_id = tenant_id
        self.__validate_credentials()
        self.__emulator_mode = ad_app_id is None or ad_app_secret is None or tenant_id is None
        self.__token = None

    def __validate_credentials(self):
        missing_credentials = self.__ad_app_id is None or self.__ad_app_secret is None
        should_enable_client = self.__ad_app_id is not None or self.__ad_app_secret is not None
        if should_enable_client and missing_credentials:
            raise Exception("Missing at least one of the following variables: AZURE_AD_APP_ID and AZURE_AD_APP_SECRET. Please, check your configuration.")

    def is_configured(self):
        return self.__tenant_id is not None and self.__ad_app_id is not None and self.__ad_app_secret is not None

    def get_user_by_id(self, user_id):
        res = requests.get(
            f"https://graph.microsoft.com/beta/users/{user_id}",
            headers=self.__get_default_headers()
        )
        try:
            res.raise_for_status()
        except Exception as e:
            if res.status_code == 401:
                self.__raise_auth_exception()
            log.error(str(e))
            raise e
        return res.json()

    def get_team_by_name(self, team_name):
        response = requests.get(
            f"https://graph.microsoft.com/beta/teams",
            params={'$filter': f"displayName eq '{team_name}'"},
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
        except Exception as e:
            if response.status_code == 401:
                self.__raise_auth_exception()
            log.error(f'unable to find the team "{team_name}": {str(e)}')
            raise Exception(f"An Admin Team was defined but it's unreachable.")
        return response.json().get('value')[0]

    def get_default_channel_from_team(self, team_id):
        response = requests.get(
            f"https://graph.microsoft.com/beta/teams/{team_id}/channels",
            params={'$filter': "moderationSettings eq null"},
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
        except Exception as e:
            if response.status_code == 401:
                self.__raise_auth_exception()
            log.error(f'unable to find the default channel of the team "{team_id}": {str(e)}')
            raise Exception(f"The Default Channel of the defined Admin Team is unreachable.")
        serialized_channel = response.json().get('value')[0]
        serialized_channel['displayName'] = None
        return serialized_channel

    def get_channel_by_name(self, team_id, channel_name):
        response = requests.get(
            f"https://graph.microsoft.com/beta/teams/{team_id}/channels",
            params={'$filter': f"displayName eq '{channel_name}'"},
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
        except Exception as e:
            if response.status_code == 401:
                self.__raise_auth_exception()
            log.error(f'unable to find the channel "{channel_name}": {str(e)}')
            raise Exception(f"An Admin Channel was defined but it's unreachable.")
        return response.json().get('value')[0]

    def get_channel_by_id(self, team_id, channel_id):
        response = requests.get(
            f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{channel_id}",
            headers=self.__get_default_headers()
        )
        try:
            response.raise_for_status()
        except Exception as e:
            if response.status_code == 401:
                self.__raise_auth_exception()
            log.error(f'unable to find the channel by id: {str(e)}')
            raise Exception(f"An Admin Channel was defined but it's unreachable.")
        return response.json().get('value')[0]

    def __get_default_headers(self):
        headers = {
            'Content-Type': 'application/json'
        }
        if not self.__emulator_mode:
            access_token = self.__get_token()
            headers['Authorization'] = 'Bearer ' + access_token
        return headers

    def __get_token(self):
        now = datetime.datetime.now()
        if not self.__token or self.__token.expired_at <= now:
            return self.__auth()
        return self.__token.access_token

    def __auth(self):
        form = {
            'grant_type': 'client_credentials',
            'scope': 'https://graph.microsoft.com/.default',
            'client_id': self.__ad_app_id,
            'client_secret': self.__ad_app_secret,
        }
        res = requests.post(
            f'https://login.microsoftonline.com/{self.__tenant_id}/oauth2/v2.0/token',
            data=form
        )
        try:
            res.raise_for_status()
        except Exception as e:
            if res.status_code == 401:
                self.__raise_auth_exception()
            log.error(str(e))
            raise e
        data = res.json()
        expires_in = data.get('expires_in')
        expired_at = from_now(expires_in)
        self.__token = authtoken(data.get('access_token'), expired_at)
        return self.__token.access_token

    def __raise_auth_exception(self):
        log.error("We couldn't authorize on microsoft graph api. Please, verify your AZURE_AD_TENANT_ID, AZURE_AD_APP_ID and AZURE_AD_APP_SECRET and then try again.")
        raise Exception("Error with azure authorization.")


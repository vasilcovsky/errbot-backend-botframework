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
        missing_credentials = self.__tenant_id is None or self.__ad_app_id is None or self.__ad_app_secret is None
        should_enable_client = self.__tenant_id is not None or self.__ad_app_id is not None or self.__ad_app_secret is not None
        if should_enable_client and missing_credentials:
            raise Exception("Missing at least one of the following variables: AZURE_AD_TENANT_ID, AZURE_AD_APP_ID and AZURE_AD_APP_SECRET. Please, check your configuration.")

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


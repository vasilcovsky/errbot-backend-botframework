import os

class DummyConfig:
    def __init__(self, identity):
        self.BOT_IDENTITY = identity
        self.BOT_PREFIX = 'ERRBOT_BACKEND_FRAMEWORK_TEST'
        self.BOT_ASYNC = True
        self.BOT_ASYNC_POOLSIZE = 64
        self.BOT_ALT_PREFIX_CASEINSENSITIVE = True
        self.BOT_ALT_PREFIXES = ['errbot_backend']
        self.MESSAGE_SIZE_LIMIT = 1024

def mock_config():
    return DummyConfig({
        'app_id': 'AZURE_APP_ID',
        'app_password': 'AZURE_APP_PASSWORD',
        'ad_tenant_id': 'AZURE_APP_PASSWORD',
        'ad_app_id': 'AZURE_APP_PASSWORD',
        'ad_app_secret': 'AZURE_APP_PASSWORD',
    })

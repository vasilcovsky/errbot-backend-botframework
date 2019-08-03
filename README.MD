# Bot Framework Backend for ErrBot

Backend for [Bot Framework](https://botframework.com) that brings ErrBot to the channels: 
  * Microsoft Teams
  * Skype (COM component is not required anymore)
  * Skype for Business
  * Facebook Messenger
  * Twilio
  * Kik
  * SMS
  * Telegram
  * Slack
  * and more

![Example](https://raw.github.com/vasilcovsky/errbot-backend-botframework/master/static/example.png)

## Installation

You would need Azure account (sorry). But don't worry you don't need to pay or bring your infrastructure to Azure, just account.

 * Go to [Azure Portal](https://portal.azure.com)
 * Go to "Create New Resource" - AI + Cognitive Services - **Bot Channel Registration**
 * Fill the form and obtain the application id and secret

Download backend:
```
git clone https://github.com/vasilcovsky/errbot-backend-botframework.git
```

In errbot's config.py
```
BACKEND = 'BotFramework'  
BOT_EXTRA_BACKEND_DIR = '/path-to/errbot-backend-botframework/'

BOT_IDENTITY = {
    'appId': '<application id>',
    'appPassword': '<app secret>'
}
``` 

Start bot and activate Webserver plugin (**required**)

Final steps:
 * Go to [Azure Portal](https://portal.azure.com) 
 * Open settings
 * Specify Messaging Endpoint: https://errbot-url/botframework
 * Add channels 
 * Enjoy
 

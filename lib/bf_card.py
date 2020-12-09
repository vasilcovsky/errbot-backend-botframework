def convert_color(color):
    # WTF!? Microsoft!?
    if color == "red":
        return "attention"
    elif color == "yellow":
        return "warning"
    elif color == "green":
        return "good"
    elif color == "blue":
        return "accent"
    return "default"


def build_bf_card(card):
    title = card.title
    if card.link is not None:
        title = "[%s](%s)" % (card.title, card.link)
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.2",
            "body": [
                {
                    "type": "Container",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": title,
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": convert_color(card.color)
                        }
                    ]
                },
                {
                    "type": "Container",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": card.body,
                            "wrap": True,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {
                                    "title": t,
                                    "value": v
                                } for t, v in card.fields
                            ]
                        }
                    ]
                }
            ]
        }
    }